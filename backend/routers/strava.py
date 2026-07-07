import logging; logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query
from services.strava_client import StravaClient
from database import Activity, get_db
from routers.auth import require_session

def _get_saved_ftp(default=236):
    try:
        import json, os
        path = os.path.join(os.path.dirname(__file__), "data", "ftp_setting.json")
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f).get("ftp", default)
    except Exception:
        pass
    return default

from datetime import datetime, timedelta
from fastapi import Request
import os

router = APIRouter(prefix="/api/strava", tags=["strava"])

def get_strava():
    return StravaClient(
        client_id=os.environ.get("STRAVA_CLIENT_ID", "81612"),
        client_secret=os.environ.get("STRAVA_CLIENT_SECRET", "b0b204b5425e5ba48bc3d55d89f3412b5f1a7fc2")
    )

@router.post("/import-activities")
def import_activities(limit: int = 50, db = Depends(get_db), client: StravaClient = Depends(get_strava), _session=Depends(require_session)):
    """Import activities from Strava to local database"""
    
    all_activities = client.get_activities(limit=limit)
    
    imported = 0
    skipped = 0
    
    for act in all_activities:
        strava_id = str(act.get("id"))
        existing = db.query(Activity).filter(Activity.source_file == f"strava:{strava_id}").first()
            
        if existing:
            skipped += 1
            continue
        
        start_time = None
        if act.get("start_date_local"):
            try:
                start_time = datetime.fromisoformat(act["start_date_local"].replace("Z", "+00:00"))
            except Exception:
                pass
        
        elapsed = act.get("elapsed_time", 0)
        end_time = None
        if start_time and elapsed:
            end_time = start_time + timedelta(seconds=elapsed)
        
        new_activity = Activity(
            name=act.get("name", "Activity"),
            sport=act.get("type", "Ride"),
            start_time=start_time,
            end_time=end_time,
            timezone=act.get("timezone", "UTC"),
            source_file=f"strava:{strava_id}",
            file_format="strava",
            distance_m=act.get("distance", 0) or 0,
            moving_time_s=act.get("moving_time", 0) or 0,
            elapsed_time_s=act.get("elapsed_time", 0) or 0,
            avg_speed_ms=act.get("average_speed", 0) or 0,
            max_speed_ms=act.get("max_speed", 0) or 0,
            elevation_gain_m=act.get("total_elevation_gain", 0) or 0,
            avg_heartrate=act.get("average_heartrate"),
            max_heartrate=act.get("max_heartrate"),
            avg_power_w=act.get("average_watts"),
            max_power_w=act.get("max_watts"),
            avg_cadence=act.get("average_cadence"),
        )
        
        db.add(new_activity)
        db.flush()
        
        try:
            new_activity.streams = client.get_streams(strava_id)
        except Exception:
            pass
        
        # Compute NP/TSS/IF/calories from streams, or estimate from avg_power
        if new_activity.streams and new_activity.streams.get("watts", {}).get("data"):
            m = _compute_power_metrics(new_activity.streams)
            if m:
                new_activity.normalized_power_w = m["np"]
                new_activity.intensity_factor = m["if_val"]
                new_activity.tss = m["tss"]
                new_activity.calories_kcal = m["calories"]
        else:
            if new_activity.avg_power_w and new_activity.moving_time_s:
                ap = new_activity.avg_power_w
                ftp = _get_saved_ftp()
                # Estimate NP as ~1.03x avg power for steady rides, up to 1.15x for punchy
                est_np = min(ap * 1.10, new_activity.max_power_w or ap * 1.3)
                if_val = round(est_np / ftp, 2) if ftp > 0 else 0
                tss_val = round((new_activity.moving_time_s * est_np * if_val) / (ftp * 3600) * 100, 1) if ftp > 0 else 0
                cal_val = round(ap * new_activity.moving_time_s / 1000)
                new_activity.normalized_power_w = round(est_np, 1)
                new_activity.intensity_factor = if_val
                new_activity.tss = tss_val
                new_activity.calories_kcal = cal_val
        

                ftp = _get_saved_ftp()
                try:
                    import json, os
                    with open(os.path.join(os.path.dirname(__file__), "data", "ftp_setting.json")) as fp:
                        ftp = json.load(fp).get("ftp", 236)
                except Exception:
                    pass

        imported += 1
        try:
            new_activity.ai_insight = _generate_insight_for(new_activity)
        except Exception:
            pass
    
    try:
        db.commit()
    except Exception:
        db.rollback()
        imported = max(0, imported - 1)
        skipped += 1
    if imported > 0:
        # Trigger PMC backfill + coach note in background process
        try:
            import subprocess, sys, os
            subprocess.Popen(
                [sys.executable, "-c", "import os; exec(open('/opt/cyclestats/backend/scripts/daily_coach.py').read())"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env={**os.environ}
            )
        except Exception:
            pass
    
    return {"imported": imported, "skipped": skipped, "total": len(all_activities)}

@router.post("/backup-streams")
def backup_streams(limit: int = 50, db = Depends(get_db), client: StravaClient = Depends(get_strava), _session=Depends(require_session)):
    activities = db.query(Activity).filter(
        Activity.source_file.like("strava:%"),
        Activity.streams == None
    ).limit(limit).all()
    
    backed_up = 0
    for act in activities:
        strava_id = act.source_file.replace("strava:", "")
        try:
            act.streams = client.get_streams(strava_id)
            backed_up += 1
        except Exception:
            pass
    
    db.commit()
    return {"backed_up": backed_up, "total": len(activities)}


@router.get("/status")
def strava_status(_session = Depends(require_session)):
    """Check if Strava is connected."""
    import os, json
    state_path = "/opt/cyclestats/backend/data/strava_state.json"
    if os.path.exists(state_path):
        try:
            with open(state_path) as f:
                state = json.load(f)
            if state.get("access_token"):
                return {"connected": True, "athlete": "Strava"}
        except Exception:
            pass
    return {"connected": False, "athlete": None}

@router.post("/connect")
def strava_connect(token: str = Query(None), _session=Depends(require_session)):
    """Save a Strava access token."""
    import os, json
    if not token:
        raise HTTPException(status_code=400, detail="Token required")
    state_path = "/opt/cyclestats/backend/data/strava_state.json"
    try:
        with open(state_path, "w") as f:
            json.dump({"access_token": token, "refresh_token": "", "expires_at": 0}, f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"connected": True, "athlete": "Strava"}

@router.post("/disconnect")



@router.get("/setup-instructions")
def strava_setup_instructions(_session = Depends(require_session)):
    """Get instructions for setting up your own Strava API application."""
    return {
        "steps": [
            "1. Go to https://www.strava.com/settings/api and log in",
            "2. Under 'My API Application', click 'Create Your App'",
            "3. Fill in: Application Name = 'CycleStats' (or anything)",
            "4. Website = 'https://192.168.86.193'",
            "5. Authorization Callback Domain = '192.168.86.193'",
            "6. Click 'Create'",
            "7. Copy your Client ID and Client Secret",
            "8. Set them in the terminal:",
            "   ssh root@192.168.86.193",
            "   mkdir -p /etc/systemd/system/cyclestats.service.d",
            '   cat > /etc/systemd/system/cyclestats.service.d/strava.conf << "EOF"',
            "   [Service]",
            "   Environment=STRAVA_CLIENT_ID=your_client_id",
            "   Environment=STRAVA_CLIENT_SECRET=your_client_secret",
            "   EOF",
            "   systemctl daemon-reload && systemctl restart cyclestats",
            "9. Then click 'Connect Strava' here in the settings page"
        ]
    }


@router.get("/auth-url")
def strava_auth_url(client: StravaClient = Depends(get_strava),         _session = Depends(require_session)):
    """Get Strava OAuth authorization URL."""
    from urllib.parse import quote
    redirect_uri = "https://cyclestats.colahan.cc/api/strava/callback"
    url = client.get_auth_url(quote(redirect_uri, safe=''))
    return {"auth_url": url, "redirect_uri": redirect_uri, "note": "If you get a redirect_uri error, see /api/strava/setup-instructions"}

@router.get("/callback")
def strava_callback(code: str = None, error: str = None, client: StravaClient = Depends(get_strava),         _session = Depends(require_session)):
    """Handle Strava OAuth callback."""
    from fastapi.responses import HTMLResponse
    if error:
        return HTMLResponse(
            '<html><body style="font-family:sans-serif;background:#0f1117;color:#e4e6ef;display:flex;align-items:center;justify-content:center;height:100vh;text-align:center;">'
            '<div><h1 style="color:#ef5350;">Authorization Failed</h1><p style="color:#8b8fa3;">' + error + '</p>'
            '<p style="margin-top:24px;"><a href="/" style="color:#6366f1;">Back to CycleStats</a></p></div></body></html>',
            status_code=400
        )
    if not code:
        return HTMLResponse(
            '<html><body style="font-family:sans-serif;background:#0f1117;color:#e4e6ef;display:flex;align-items:center;justify-content:center;height:100vh;text-align:center;">'
            '<div><h1 style="color:#ef5350;">No authorization code received</h1><p><a href="/" style="color:#6366f1;">Back to CycleStats</a></p></div></body></html>',
            status_code=400
        )
    try:
        data = client.exchange_code(code, "https://cyclestats.colahan.cc/api/strava/callback")
        athlete = data.get("athlete", {})
        name = athlete.get("firstname", "") + " " + athlete.get("lastname", "")
        return HTMLResponse(
            '<html><body style="font-family:sans-serif;background:#0f1117;color:#e4e6ef;display:flex;align-items:center;justify-content:center;height:100vh;text-align:center;">'
            '<div><h1 style="color:#34d399;">Strava Connected!</h1>'
            '<p style="color:#8b8fa3;margin:16px 0;">Connected as <strong>' + name.strip() + '</strong></p>'
            '<p style="margin-top:24px;"><a href="/" style="color:#6366f1;">Back to Dashboard</a></p></div></body></html>'
        )
    except Exception as e:
        return HTMLResponse(
            '<html><body style="font-family:sans-serif;background:#0f1117;color:#e4e6ef;display:flex;align-items:center;justify-content:center;height:100vh;text-align:center;">'
            '<div><h1 style="color:#ef5350;">Token Exchange Failed</h1><p style="color:#8b8fa3;">' + str(e) + '</p>'
            '<p><a href="/" style="color:#6366f1;">Back to CycleStats</a></p></div></body></html>',
            status_code=400
        )

@router.get("/me")
def strava_me(client: StravaClient = Depends(get_strava),         _session = Depends(require_session)):
    """Get current Strava athlete info."""
    try:
        athlete = client.get_athlete()
        return {
            "id": athlete.get("id"),
            "firstname": athlete.get("firstname"),
            "lastname": athlete.get("lastname"),
            "city": athlete.get("city"),
            "country": athlete.get("country"),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

def strava_disconnect(_session=Depends(require_session)):
    """Remove Strava tokens."""
    import os
    state_path = "/opt/cyclestats/backend/data/strava_state.json"
    if os.path.exists(state_path):
        os.remove(state_path)
    return {"connected": False}

@router.get("/activities")
def strava_activities(limit: int = 30, client: StravaClient = Depends(get_strava), _session=Depends(require_session)):
    """List recent Strava activities."""
    try:
        acts = client.get_activities(limit=limit)
        return acts
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/activities/{strava_id}/streams")
def strava_activity_streams(strava_id: int, client: StravaClient = Depends(get_strava), _session=Depends(require_session)):
    """Get streams for a Strava activity."""
    try:
        streams = client.get_streams(strava_id)
        return streams
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/segments")
def strava_segments(client: StravaClient = Depends(get_strava), _session=Depends(require_session)):
    """Get starred Strava segments."""
    try:
        return client.get_starred_segments()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/segments/{segment_id}/leaderboard")
def strava_segment_leaderboard(segment_id: int):
    """Placeholder for segment leaderboard."""
    return {"segment_name": "Unknown", "effort_count": 0, "results": []}


def _generate_activity_insight(act, db) -> str:
    """Generate a rich coaching insight for a single activity."""
    import json
    from datetime import datetime, timedelta
    parts = []
    sport = act.sport or "Ride"
    duration_h = (act.moving_time_s or 0) / 3600
    dist_km = (act.distance_m or 0) / 1000
    if duration_h > 3:
        parts.append(f"Long {sport.lower()} at {duration_h:.1f}h / {dist_km:.0f}km")
    elif duration_h > 1:
        parts.append(f"{sport} lasting {duration_h:.1f}h / {dist_km:.1f}km")
    elif duration_h < 0.5 and act.tss and act.tss < 30:
        parts.append(f"Short recovery {sport.lower()} ({duration_h*60:.0f}min)")
    else:
        parts.append(f"{sport} ({duration_h*60:.0f}min, {dist_km:.1f}km)")
    if act.avg_power_w and act.normalized_power_w:
        np = act.normalized_power_w
        if_val = act.intensity_factor or (np / 236 if 236 > 0 else 0)
        parts.append(f"NP {np:.0f}W, AP {act.avg_power_w:.0f}W, IF {if_val:.2f}")
        if if_val > 1.0: parts.append("above-threshold effort")
        elif if_val > 0.85: parts.append("solid threshold work")
        elif if_val > 0.7: parts.append("steady tempo effort")
    elif act.avg_power_w:
        parts.append(f"AP {act.avg_power_w:.0f}W")
    if act.streams:
        try:
            s = json.loads(act.streams) if isinstance(act.streams, str) else act.streams
            pw = None
            if s and "watts" in s:
                w = s["watts"]
                pw = w.get("data", w) if isinstance(w, dict) else w
            elif s and "power" in s:
                p = s["power"]
                pw = p.get("data", p) if isinstance(p, dict) else p
            if pw:
                clean = [x for x in pw if x and x > 0]
                if clean:
                    ftp = 236
                    z = {1:0,2:0,3:0,4:0,5:0,6:0,7:0}
                    for v in clean:
                        pct = v / ftp * 100
                        if pct < 55: z[1] += 1
                        elif pct < 75: z[2] += 1
                        elif pct < 90: z[3] += 1
                        elif pct < 105: z[4] += 1
                        elif pct < 120: z[5] += 1
                        elif pct < 150: z[6] += 1
                        else: z[7] += 1
                    total = sum(z.values()) or 1
                    z_names = {1:"Recovery",2:"Endurance",3:"Tempo",4:"Threshold",5:"VO2Max",6:"Anaerobic",7:"Neuromuscular"}
                    top_z = max(z, key=z.get)
                    top_pct = z[top_z] / total * 100
                    if top_pct > 35:
                        parts.append(f"predominantly Z{top_z} {z_names[top_z]} ({top_pct:.0f}% of power time)")
                    z5_7 = z[5] + z[6] + z[7]
                    if z5_7 / total > 0.15: parts.append(f"{z5_7/total*100:.0f}% above threshold - high intensity")
                    if z[2] / total > 0.50: parts.append(f"{(z[2]/total*100):.0f}% in Z2 - solid base endurance")
        except: pass
    if act.elevation_gain_m:
        if act.elevation_gain_m > 1000: parts.append(f"{act.elevation_gain_m:.0f}m climbing - serious elevation")
        elif act.elevation_gain_m > 300: parts.append(f"{act.elevation_gain_m:.0f}m gain")
    if act.tss:
        if act.tss > 200: parts.append(f"TSS {act.tss:.0f} - significant training load, plan recovery")
        elif act.tss > 100: parts.append(f"TSS {act.tss:.0f} - moderate training stimulus")
        else: parts.append(f"TSS {act.tss:.0f} - light day")
    if act.calories_kcal and act.calories_kcal > 1500:
        parts.append(f"{act.calories_kcal:.0f}kCal burned - refuel well")
    return ". ".join(parts) + "."

from services.hr_analysis import compute_hr_metrics

def _generate_insight_for(act):
    """Generate AI insight text for a single activity."""
    streams = act.streams or {}
    parts = []
    tip_parts = []
    
    dur_h = act.moving_time_s / 3600 if act.moving_time_s else 0
    dist_km = (act.distance_m or 0) / 1000
    
    if dur_h > 4:
        parts.append("Long ride at {:.1f}h / {:.0f}km".format(dur_h, dist_km))
    elif dur_h > 2:
        parts.append("Medium ride at {:.1f}h / {:.0f}km".format(dur_h, dist_km))
    elif dur_h > 0.5:
        parts.append("Quick ride at {:.1f}h / {:.0f}km".format(dur_h, dist_km))
    else:
        parts.append("Short effort at {:.1f}h / {:.0f}km".format(dur_h, dist_km))
    
    if act.normalized_power_w:
        if_val = act.intensity_factor or 0
        if if_val < 0.75: intensity = "endurance"
        elif if_val < 0.90: intensity = "tempo"
        elif if_val < 1.05: intensity = "threshold"
        else: intensity = "hard"
        parts.append("NP {:.0f}W, AP {}W, IF {:.2f} ({})".format(act.normalized_power_w, act.avg_power_w or "?", if_val, intensity))
    
    if act.elevation_gain_m and act.elevation_gain_m > 200:
        parts.append("{:.0f}m gain".format(act.elevation_gain_m))
    
    hr_metrics = compute_hr_metrics(streams)
    if hr_metrics:
        parts.append("Avg HR {:.0f}bpm, max {}bpm".format(hr_metrics['avg_hr'], hr_metrics['max_hr']))
        z = hr_metrics.get('hr_zone_pcts', {})
        if z:
            primary = max(z, key=z.get)
            parts.append("predominantly {} ({}% of HR time)".format(primary, z[primary]))
        drift = hr_metrics.get('cardiac_drift_pct')
        if drift is not None and drift > 10:
            parts.append("cardiac drift {:.1f}% - HR rising".format(drift))
    
    # ── Tip Generation ──────────────────────────────────────────
    import random
    tip_pool = []
    
    # 1. Cardiac drift tip (highest priority - health/safety)
    if hr_metrics:
        drift = hr_metrics.get('cardiac_drift_pct')
        ef = hr_metrics.get('efficiency_factor')
        if drift is not None:
            if drift > 15:
                tip_pool.append(random.choice([
                    "Cardiac drift of {:.1f}% is significant — pre-hydrate better and consider electrolyte replacement during rides over 90 minutes".format(drift),
                    "High cardiac drift ({:.1f}%) suggests you started under-fuelled or dehydrated. Try a bigger pre-ride breakfast and sip regularly".format(drift),
                    "Your HR drifted {:.1f}% over the ride — heat and fatigue are compounding. Plan cooler start times or more frequent water stops".format(drift),
                ]))
            elif drift > 10:
                tip_pool.append(random.choice([
                    "Mild cardiac drift ({:.1f}%) — staying on top of hydration and pacing will keep this in check".format(drift),
                    "Some HR drift ({:.1f}%) is normal on longer efforts. Your fitness is solid, just watch fluid intake".format(drift),
                ]))
        
        # Efficiency factor tip
        if ef is not None and act.normalized_power_w:
            if ef > 1.4:
                tip_pool.append(random.choice([
                    "Excellent efficiency ({:.2f} P:HR) — you're producing good power for your heart rate. Aerobic engine is strong".format(ef),
                    "Your power-to-heart-rate ratio ({:.2f}) is impressive for this intensity. Aerobic conditioning looks sharp".format(ef),
                ]))
            elif ef < 0.9 and act.normalized_power_w > 150:
                tip_pool.append(random.choice([
                    "Efficiency factor ({:.2f}) is low for the power output — could indicate accumulated fatigue or a hard effort at your limit".format(ef),
                    "P:HR ratio of {:.2f} is lower than ideal at this power level. Consider whether you're fully recovered".format(ef),
                ]))
    
    # 2. IF-based training tips
    if_val = act.intensity_factor or 0
    if if_val > 0:
        if if_val < 0.55:
            tip_pool.append(random.choice([
                "Z1 recovery pace — these easy spins clear lactate and build aerobic base without adding fatigue",
                "Easy riding like this promotes blood flow and recovery. Perfect between hard sessions",
                "Active recovery at IF {:.2f} — these rides matter more than most people think for long-term fitness".format(if_val),
            ]))
        elif if_val < 0.70:
            tip_pool.append(random.choice([
                "Solid Z2 endurance work — this builds mitochondrial density and capillary networks. The bread and butter of aerobic fitness",
                "Endurance tempo at IF {:.2f} — consistent time in Z2 is what grows your aerobic engine sustainably".format(if_val),
                "Good base-building effort. These rides compound over weeks — every hour in Z2 raises your long-term ceiling",
                "Sweet spot of endurance training — hard enough to stimulate adaptation, easy enough to repeat tomorrow",
            ]))
        elif if_val < 0.80:
            tip_pool.append(random.choice([
                "Tempo effort at IF {:.2f} — this is where you start to see real FTP gains. Great work maintaining this".format(if_val),
                "Upper Z2 / low tempo — the 'sweet spot' many coaches target. Efficient training stimulus with manageable fatigue",
                "Consistent tempo riding teaches your body to sustain higher power outputs. This pays off on race day",
            ]))
        elif if_val < 0.90:
            tip_pool.append(random.choice([
                "Threshold-adjacent work at IF {:.2f} — this effort pushes your lactate tolerance and raises FTP over time".format(if_val),
                "Strong tempo-to-threshold effort. Rides like this build the ability to hold high power for extended periods",
                "Good solid effort — repeated sessions in this range are what push your FTP up meaningfully",
            ]))
        elif if_val < 1.05:
            tip_pool.append(random.choice([
                "Threshold effort! IF {:.2f} is right at FTP level — this is the most productive training zone for raising your ceiling".format(if_val),
                "FTP-challenging work. Sessions at this intensity require good recovery afterward but deliver big fitness gains",
                "Riding at threshold builds mental toughness and physiological capacity. Strong effort",
            ]))
        else:
            tip_pool.append(random.choice([
                "High intensity effort at IF {:.2f} — these take it out of you. Prioritise recovery: easy spin tomorrow and extra sleep".format(if_val),
                "Anaerobic work at IF {:.2f} — this drives neuromuscular adaptations but demands proper recovery".format(if_val),
                "Big effort — IF above 1.0 means you were deep in the red. Refuel well tonight and take it easy tomorrow",
            ]))
    
    # 3. Duration-specific tips
    dur_h = act.moving_time_s / 3600 if act.moving_time_s else 0
    if dur_h > 5:
        tip_pool.append(random.choice([
            "Epic ride at {:.1f}h — nutrition timing is everything on these. Aim for 60-90g carb per hour and stay ahead of thirst".format(dur_h),
            "Over 5 hours in the saddle — you're building serious endurance. Focus on post-ride recovery nutrition within 30 minutes",
            "That's a big day out ({:.1f}h). Your body absorbed a lot of stress — easy week ahead to let adaptations sink in".format(dur_h),
        ]))
    elif dur_h > 3:
        tip_pool.append(random.choice([
            "Strong ride length ({:.1f}h) — good endurance stimulus without going deep into depletion".format(dur_h),
            "Three-plus hour rides like this are the backbone of base training. Consistent weeks of these build real fitness",
        ]))
    elif dur_h < 1 and if_val < 0.65:
        tip_pool.append(random.choice([
            "Short and easy — these active recovery sessions help clear fatigue without adding training stress",
            "Quick spin — perfect for recovery between harder efforts. Your legs will thank you tomorrow",
        ]))
    
    # 4. TSS/recovery awareness
    if act.tss:
        if act.tss > 180:
            tip_pool.append(random.choice([
                "TSS of {:.0f} is a very heavy load — take a rest day or easy spin tomorrow to absorb the training effect".format(act.tss),
                "Big TSS day ({:.0f}). Your body needs recovery time proportionate to the stress. Prioritise sleep and nutrition".format(act.tss),
            ]))
        elif act.tss > 130:
            tip_pool.append(random.choice([
                "TSS {:.0f} is a solid training stimulus — your fitness is growing. Watch cumulative fatigue if you stack these".format(act.tss),
                "Good training load ({:.0f} TSS) — meaningful enough to drive adaptation, sustainable enough to repeat".format(act.tss),
            ]))
    
    # 5. Hill/climbing tips
    if act.elevation_gain_m and (act.distance_m or 0) > 0:
        gain_per_km = act.elevation_gain_m / (act.distance_m / 1000)
        if gain_per_km > 30:
            tip_pool.append(random.choice([
                "Climbing-heavy ride at {:.0f}m/km — each ascent builds leg strength and power-to-weight. Great for FTP development".format(gain_per_km),
                "That's serious vert ({:.0f}m/km) — climbing like this is one of the most effective ways to build functional strength on the bike".format(gain_per_km),
            ]))
        elif gain_per_km > 15:
            tip_pool.append(random.choice([
                "Rolling terrain with {:.0f}m/km of climbing — these undulating rides build versatility and power endurance".format(gain_per_km),
                "Good mix of flats and climbs — varied terrain makes for a well-rounded training stimulus",
            ]))
    
    # 6. Combined situational tips
    if dur_h > 2 and if_val < 0.65:
        tip_pool.append(random.choice([
            "Long at low intensity — this is textbook base building. Five to six of these a week and your CTL will climb steadily",
            "Endurance ride done right — controlled effort, good duration. This builds the foundation for everything else",
        ]))
    elif dur_h > 3 and if_val > 0.70:
        tip_pool.append(random.choice([
            "Long AND steady tempo — these are the killer sessions that build both aerobic depth and sustainable power",
            "A proper endurance-plus session. These are hard but incredibly productive for race readiness",
        ]))
    
    # 7. Pick the best tip
    if tip_pool:
        # Pick the most specific/contextual tip if multiple exist
        # Prefer drift/HR tips if they exist
        chosen = tip_pool[0]
        # If there are multiple tips, prefer drift -> TSS -> IF -> duration -> climbing order
        tip_parts.append(chosen)
    
    if act.tss:
        if act.tss > 150: label = "heavy"
        elif act.tss > 80: label = "moderate"
        else: label = "light"
        parts.append("TSS {:.0f} - {} training load".format(act.tss, label))
    
    if act.calories_kcal:
        parts.append("{:.0f}kCal burned".format(act.calories_kcal))
    
    main = ". ".join(p for p in parts) + "." if parts else ""
    if tip_parts:
        main += " |TIP: " + tip_parts[0]
    
    return main


def _compute_power_metrics(streams, ftp=None):
    if ftp is None:
        import json, os
        try:
            with open(os.path.join(os.path.dirname(__file__), "data", "ftp_setting.json")) as f:
                ftp = json.load(f).get("ftp", 236)
        except Exception as e:
            ftp = 236
    """Compute NP, TSS, IF, calories from power stream data."""
    wd = streams.get("watts", {})
    watts = wd.get("data", []) if isinstance(wd, dict) else (wd or [])
    if len(watts) < 30:
        return {}
    valid = [w for w in watts if w and w > 0]
    if not valid:
        return {}
    window = 30
    smoothed = []
    for i in range(len(watts)):
        s = max(0, i - window + 1)
        chunk = [w for w in watts[s:i+1] if w and w > 0]
        if chunk:
            smoothed.append(sum(chunk) / len(chunk))
    if not smoothed:
        return {}
    fourth = sum(v**4 for v in smoothed if v > 0) / len(smoothed)
    np = round(fourth ** 0.25, 1)
    if_val = round(np / ftp, 2) if ftp > 0 else 0
    ap = round(sum(valid) / len(valid), 1)
    td = streams.get("time", {})
    tv = td.get("data", []) if isinstance(td, dict) else (td or [])
    ds = tv[-1] if tv else 0
    tss = round((ds * np * if_val) / (ftp * 3600) * 100, 1) if ftp > 0 else 0
    cal = round(ap * ds / 1000) if ds > 0 else 0
    return {"np": np, "if_val": if_val, "tss": tss, "calories": cal}
