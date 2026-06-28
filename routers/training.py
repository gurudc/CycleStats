from routers.auth import require_session
from routers.auth import require_session
"""Training load and power-duration endpoints."""
import logging
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from database import get_db, Activity, DailyTrainingLoad, HealthCheckin
from services.power_duration import (
    compute_mmp_curve, compute_power_curve, compute_power_profile,
    compute_ftp_cached, compute_activity_power_duration,
    estimate_ftp, estimate_awc, compute_xss,
)
from services.training_load import get_pmc, update_training_load

router = APIRouter(prefix="/api/training", tags=["training"])
logger = logging.getLogger(__name__)


@router.get("/pmc")
def performance_management_chart(days: int = 90, db: Session = Depends(get_db),         _session = Depends(require_session)):
    """Get Performance Management Chart (CTL/ATL/TSB) data."""
    return get_pmc(db, days)


@router.post("/recompute")
def recompute_training_load(db: Session = Depends(get_db), ftp: float = None,         _session = Depends(require_session)):
    """Recompute all training load metrics."""
    import json, os
    # Persist FTP setting
    if ftp is not None:
        ftp_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "ftp_setting.json")
        os.makedirs(os.path.dirname(ftp_file), exist_ok=True)
        with open(ftp_file, "w") as f:
            json.dump({"ftp": ftp}, f)
    result = update_training_load(db, ftp)
    return result


@router.get("/power-curve")
def power_curve(db: Session = Depends(get_db),         _session = Depends(require_session)):
    """Get the all-time best power-duration curve (cached)."""
    curve = compute_power_curve(db)
    return {"curve": curve}


@router.get("/power-profile")
def power_profile(db: Session = Depends(get_db), ftp: float = None,         _session = Depends(require_session)):
    """Get power profile (5s, 1m, 5m, 20m, FTP) — cached."""
    profile = compute_power_profile(db, ftp)
    return {"profile": profile}


@router.get("/ftp")
def ftp_estimate(db: Session = Depends(get_db),         _session = Depends(require_session)):
    """Estimate FTP from historical data or use persisted setting."""
    import json, os
    ftp_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "ftp_setting.json")
    if os.path.exists(ftp_file):
        try:
            with open(ftp_file) as f:
                saved = json.load(f)
                ftp = saved.get("ftp")
                if ftp:
                    awc, wp = 0, 0
                    return {"ftp": ftp, "awc_kj": awc, "w_prime_kj": wp, "source": "manual"}
        except Exception:
            pass
    return compute_ftp_cached(db)


@router.get("/activity-mmp/{activity_id}")
def activity_mmp(activity_id: int, db: Session = Depends(get_db),         _session = Depends(require_session)):
    """Get power-duration curve for a specific activity."""
    activity = db.query(Activity).filter(Activity.id == activity_id).first()
    if not activity or not activity.streams:
        return {"curve": {}}
    powers = activity.streams.get("power", [])
    times = activity.streams.get("time", [])
    curve = compute_activity_power_duration(powers, times)
    return {"curve": curve}


@router.get("/xss/{activity_id}")
def activity_xss(activity_id: int, db: Session = Depends(get_db), ftp: float = None,         _session = Depends(require_session)):
    """Compute XSS equivalent for an activity."""
    activity = db.query(Activity).filter(Activity.id == activity_id).first()
    if not activity or not activity.streams:
        return {"xss": None}

    if ftp is None:
        all_ids = [a.id for a in db.query(Activity.id).all()]
        mmp = compute_mmp_curve(all_ids, db)
        ftp = estimate_ftp(mmp)

    powers = activity.streams.get("power", [])
    xss = compute_xss(powers, ftp) if ftp else None
    return {"xss": xss, "ftp": ftp}


@router.get("/summary")
def training_summary(db: Session = Depends(get_db),         _session = Depends(require_session)):
    """Get a quick training summary."""
    # Latest PMC entry
    latest_pmc = db.query(DailyTrainingLoad).order_by(desc(DailyTrainingLoad.date)).first()

    # Total activities
    total_activities = db.query(Activity).count()

    # Total distance
    total_distance = db.query(db.query(Activity).with_entities(
        Activity.distance_m
    ).subquery()).selectable  # Simplified

    from sqlalchemy import func
    stats = db.query(
        func.sum(Activity.distance_m).label("total_distance"),
        func.sum(Activity.moving_time_s).label("total_time"),
        func.sum(Activity.elevation_gain_m).label("total_elevation"),
        func.sum(Activity.kilojoules_kj).label("total_kj"),
        func.count(Activity.id).label("activity_count"),
    ).first()

    return {
        "total_activities": stats.activity_count or 0,
        "total_distance_km": round((stats.total_distance or 0) / 1000, 1),
        "total_time_hours": round((stats.total_time or 0) / 3600, 1),
        "total_elevation_m": round(stats.total_elevation or 0),
        "total_kj": round(stats.total_kj or 0),
        "latest_pmc": latest_pmc.to_dict() if latest_pmc else None,
    }


@router.get("/calendar")
def training_calendar(days: int = 365, db: Session = Depends(get_db),         _session = Depends(require_session)):
    """Get daily TSS data for calendar heatmap."""
    from datetime import datetime, timedelta
    from sqlalchemy import func
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = db.query(
        func.date(Activity.start_time).label("day"),
        func.sum(Activity.tss).label("tss"),
        func.sum(Activity.kilojoules_kj).label("kj"),
        func.sum(Activity.distance_m).label("distance"),
        func.count(Activity.id).label("count"),
    ).filter(
        Activity.start_time >= cutoff,
        Activity.tss.isnot(None)
    ).group_by(
        func.date(Activity.start_time)
    ).order_by(func.date(Activity.start_time)).all()
    
    return [{
        "date": str(r.day),
        "tss": round(r.tss, 1) if r.tss else 0,
        "kj": round(r.kj) if r.kj else 0,
        "distance_km": round((r.distance or 0) / 1000, 1),
        "count": r.count or 0,
    } for r in rows]

@router.get("/sports")
def sport_list(db: Session = Depends(get_db),         _session = Depends(require_session)):
    """Get distinct sport types."""
    sports = db.query(Activity.sport).distinct().order_by(Activity.sport).all()
    return [s[0] for s in sports if s[0]]


@router.get("/zones")
def power_zones(days: int = 90, db: Session = Depends(get_db),         _session = Depends(require_session)):
    """Get power training zones and time-in-zone for recent activities."""
    import json, math
    from datetime import datetime, timedelta

    # Get FTP - manual setting, fall back to estimated
    import os as _os, json as _json
    ftp = 200
    _ftp_path = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "data", "ftp_setting.json")
    try:
        if _os.path.exists(_ftp_path):
            with open(_ftp_path) as _f:
                _saved = _json.load(_f)
                if _saved.get("ftp"):
                    ftp = _saved["ftp"]
    except Exception:
        pass
    if ftp == 200:
        from services.power_duration import compute_ftp_cached
        _ftp_data = compute_ftp_cached(db)
        ftp = _ftp_data.get("ftp", 200) or 200

    # Power zones (Coggan-style, 7 zones)
    zones = [
        {"zone": 1, "name": "Active Recovery", "low_pct": 0, "high_pct": 55, "color": "#95a5a6", "description": "Easy spinning, recovery rides"},
        {"zone": 2, "name": "Endurance", "low_pct": 55, "high_pct": 75, "color": "#27ae60", "description": "Aerobic endurance, long rides"},
        {"zone": 3, "name": "Tempo", "low_pct": 75, "high_pct": 90, "color": "#f1c40f", "description": "Moderate effort, steady state"},
        {"zone": 4, "name": "Lactate Threshold", "low_pct": 90, "high_pct": 105, "color": "#e67e22", "description": "Threshold efforts, FTP work"},
        {"zone": 5, "name": "VO2 Max", "low_pct": 105, "high_pct": 120, "color": "#e74c3c", "description": "Max aerobic power, 3-8 min intervals"},
        {"zone": 6, "name": "Anaerobic Capacity", "low_pct": 120, "high_pct": 150, "color": "#9b59b6", "description": "High-intensity efforts, 30s-3min"},
        {"zone": 7, "name": "Neuromuscular Power", "low_pct": 150, "high_pct": 300, "color": "#8e44ad", "description": "Max sprints, explosive efforts"},
    ]
    for z in zones:
        z["low_watts"] = round(z["low_pct"] / 100 * ftp)
        z["high_watts"] = round(z["high_pct"] / 100 * ftp)

    # Compute time-in-zone from recent activities
    cutoff = datetime.utcnow() - timedelta(days=days)
    activities = db.query(Activity).filter(
        Activity.start_time >= cutoff,
        Activity.streams.isnot(None)
    ).order_by(Activity.start_time.desc()).limit(50).all()

    zone_seconds = {i: 0 for i in range(1, 8)}
    total_seconds = 0
    activities_with_power = 0

    for act in activities:
        try:
            s = act.streams
            if isinstance(s, str):
                s = json.loads(s)
            power_data = None
            if "watts" in s:
                w = s["watts"]
                if isinstance(w, dict) and "data" in w:
                    power_data = w["data"]
                elif isinstance(w, list):
                    power_data = w
            elif "power" in s:
                p = s["power"]
                if isinstance(p, dict) and "data" in p:
                    power_data = p["data"]
                elif isinstance(p, list):
                    power_data = p
            if not power_data:
                continue
            clean = [x for x in power_data if x is not None and x > 0]
            if len(clean) < 10:
                continue
            activities_with_power += 1
            total_seconds += len(clean)
            for pw in clean:
                pct = (pw / ftp) * 100
                for z in zones:
                    if z["low_pct"] <= pct < z["high_pct"]:
                        zone_seconds[z["zone"]] += 1
                        break
        except Exception:
            continue

    # Build results
    zone_data = []
    for z in zones:
        secs = zone_seconds[z["zone"]]
        pct_of_total = round((secs / total_seconds * 100), 1) if total_seconds > 0 else 0
        zone_data.append({
            "zone": z["zone"],
            "name": z["name"],
            "low_watts": z["low_watts"],
            "high_watts": z["high_watts"],
            "low_pct": z["low_pct"],
            "high_pct": z["high_pct"],
            "color": z["color"],
            "description": z["description"],
            "seconds": secs,
            "hours": round(secs / 3600, 1),
            "pct_of_total": pct_of_total,
        })

    return {
        "ftp": ftp,
        "zones": zone_data,
        "total_hours": round(total_seconds / 3600, 1),
        "activities_analyzed": activities_with_power,
    }


@router.get("/insights")
def training_insights(db: Session = Depends(get_db),         _session = Depends(require_session)):
    """Compute training insights -- trends, alerts, recommendations."""
    import json, math
    from datetime import datetime, timedelta

    insights = []

    # 1. Training Load Trend (PMC)
    pmc = db.query(DailyTrainingLoad).order_by(DailyTrainingLoad.date.desc()).limit(42).all()
    pmc.reverse()
    if len(pmc) >= 7:
        latest = pmc[-1]
        week_ago = pmc[-8] if len(pmc) >= 8 else pmc[0]
        ctl_trend = round(latest.ctl - week_ago.ctl, 1)
        atl_trend = round(latest.atl - week_ago.atl, 1)
        tsb = latest.tsb or 0

        if ctl_trend > 3:
            insights.append({"type": "trend", "icon": "📈", "title": "Fitness Building", "detail": f"CTL up {ctl_trend} pts in 7 days -- fitness is growing.", "severity": "positive"})
        elif ctl_trend < -3:
            insights.append({"type": "trend", "icon": "📉", "title": "Fitness Declining", "detail": f"CTL dropped {abs(ctl_trend)} pts in 7 days -- take care not to detrain.", "severity": "warning"})

        if tsb < -15:
            insights.append({"type": "alert", "icon": "⚠️", "title": "Deep Fatigue", "detail": f"TSB is {tsb:.0f} -- you are in a performance hole. Consider several rest days.", "severity": "critical"})
        elif tsb < -5:
            insights.append({"type": "alert", "icon": "⚡", "title": "Moderate Fatigue", "detail": f"TSB is {tsb:.0f} -- fatigue is building. Plan an easy day soon.", "severity": "warning"})
        elif tsb > 15:
            insights.append({"type": "success", "icon": "🌱", "title": "Well Rested", "detail": f"TSB is {tsb:.0f} -- fresh legs! Good time for a key workout.", "severity": "positive"})

        if atl_trend > 15:
            insights.append({"type": "alert", "icon": "🔥", "title": "Spike in Fatigue", "detail": f"ATL jumped {atl_trend} pts in 7 days -- that's a big load increase.", "severity": "warning"})

    # 2. Zone Distribution
    from datetime import datetime as dt2
    cutoff = dt2.utcnow() - timedelta(days=28)
    acts = db.query(Activity).filter(Activity.start_time >= cutoff, Activity.streams.isnot(None)).all()
    zone_secs = {1:0,2:0,3:0,4:0,5:0,6:0,7:0}
    total_power_secs = 0
    for act in acts:
        try:
            s = act.streams
            if isinstance(s, str): s = json.loads(s)
            pw = None
            if "watts" in s:
                w = s["watts"]
                pw = w["data"] if isinstance(w, dict) and "data" in w else (w if isinstance(w, list) else None)
            elif "power" in s:
                p = s["power"]
                pw = p["data"] if isinstance(p, dict) and "data" in p else (p if isinstance(p, list) else None)
            if not pw: continue
            clean = [x for x in pw if x is not None and x > 0]
            total_power_secs += len(clean)
            ftp = 236
            for w in clean:
                pct = w / ftp * 100
                if pct < 55: zone_secs[1] += 1
                elif pct < 75: zone_secs[2] += 1
                elif pct < 90: zone_secs[3] += 1
                elif pct < 105: zone_secs[4] += 1
                elif pct < 120: zone_secs[5] += 1
                elif pct < 150: zone_secs[6] += 1
                else: zone_secs[7] += 1
        except: pass

    if total_power_secs > 0:
        z2_pct = zone_secs[2] / total_power_secs * 100
        z4_pct = zone_secs[4] / total_power_secs * 100
        z5_pct = zone_secs[5] / total_power_secs * 100
        if z2_pct > 35:
            insights.append({"type": "zone", "icon": "🚴", "title": "Strong Endurance Base", "detail": f"Z2 (Endurance) was {z2_pct:.0f}% of riding this month -- excellent base building.", "severity": "positive"})
        elif z2_pct < 15:
            insights.append({"type": "zone", "icon": "💨", "title": "Low Endurance Volume", "detail": f"Only {z2_pct:.0f}% in Z2 this month -- consider adding longer steady rides.", "severity": "warning"})
        if z5_pct > 8:
            insights.append({"type": "zone", "icon": "💥", "title": "High Intensity Work", "detail": f"Z5 (VO2 Max) was {z5_pct:.0f}% of riding -- solid top-end work.", "severity": "positive"})
        if z4_pct > 15:
            insights.append({"type": "zone", "icon": "⚔️", "title": "Threshold Heavy", "detail": f"Z4 (Threshold) was {z4_pct:.0f}% -- that's a lot of time at FTP. Ensure recovery between efforts.", "severity": "info"})

    # 3. Recovery (HRV trend)
    health = db.query(HealthCheckin).order_by(HealthCheckin.date.desc()).limit(14).all()
    health.reverse()
    if len(health) >= 7:
        recent_hrv = [h.hrv_rmssd for h in health[-7:] if h.hrv_rmssd]
        older_hrv = [h.hrv_rmssd for h in health[:7] if h.hrv_rmssd]
        if recent_hrv and older_hrv:
            recent_avg = sum(recent_hrv) / len(recent_hrv)
            older_avg = sum(older_hrv) / len(older_hrv)
            hrv_change = ((recent_avg - older_avg) / older_avg) * 100
            if hrv_change < -10:
                insights.append({"type": "recovery", "icon": "❤️", "title": "HRV Declining", "detail": f"HRV dropped {abs(hrv_change):.0f}% in 7 days -- sign of accumulated fatigue.", "severity": "warning"})
            elif hrv_change > 10:
                insights.append({"type": "recovery", "icon": "💚", "title": "HRV Improving", "detail": f"HRV up {hrv_change:.0f}% -- recovery is trending well.", "severity": "positive"})

        # Sleep
        sleeps = [h.sleep_hours for h in health[-7:] if h.sleep_hours]
        if sleeps:
            avg_sleep = sum(sleeps) / len(sleeps)
            if avg_sleep < 6.5:
                insights.append({"type": "sleep", "icon": "😴", "title": "Sleep Deficit", "detail": f"Avg {avg_sleep:.1f}h sleep over 7 days -- under 7h impairs recovery.", "severity": "warning"})
            elif avg_sleep >= 8:
                insights.append({"type": "sleep", "icon": "💤", "title": "Great Sleep", "detail": f"Avg {avg_sleep:.1f}h sleep -- excellent recovery foundation.", "severity": "positive"})

    # 4. Ride count & volume
    recent_rides = len([a for a in acts if a.streams])
    if recent_rides < 3:
        insights.append({"type": "volume", "icon": "📭", "title": "Low Ride Volume", "detail": f"Only {recent_rides} rides with power in 28 days -- consider increasing frequency.", "severity": "info"})
    elif recent_rides > 12:
        insights.append({"type": "volume", "icon": "💪", "title": "High Consistency", "detail": f"{recent_rides} rides in 28 days -- great consistency!", "severity": "positive"})

    if not insights:
        insights.append({"type": "info", "icon": "📊", "title": "Not Enough Data", "detail": "Sync more data from Strava or Garmin to get personalized insights.", "severity": "info"})

    return {"insights": insights, "count": len(insights)}


@router.get("/activity-insights/{activity_id}")
def activity_insights(activity_id: int, db: Session = Depends(get_db),         _session = Depends(require_session)):
    """Compute insights for a single activity."""
    import json
    from datetime import datetime

    act = db.query(Activity).filter(Activity.id == activity_id).first()
    if not act:
        return {"insights": [], "error": "Activity not found"}

    act_insights = []

    # 1. Duration and distance
    if act.moving_time_s:
        hrs = act.moving_time_s / 3600
        if hrs > 3:
            act_insights.append({"icon": "🏔️", "title": "Endurance Ride", "detail": f"Long ride at {hrs:.1f}h -- great endurance work."})
        elif hrs < 0.5:
            act_insights.append({"icon": "⚡", "title": "Short Effort", "detail": f"Only {act.moving_time_s//60}min -- likely a commuter or recovery spin."})

    if act.distance_m and act.distance_m > 80000:
        act_insights.append({"icon": "🚴", "title": "Century Ride", "detail": f"{act.distance_m/1000:.0f}km -- big day out!"})

    # 2. Elevation
    if act.elevation_gain_m:
        if act.elevation_gain_m > 1000:
            act_insights.append({"icon": "⛰️", "title": "Hilly Route", "detail": f"{act.elevation_gain_m:.0f}m climbing -- serious elevation gain."})
        elif act.elevation_gain_m < 50 and act.distance_m and act.distance_m > 30000:
            act_insights.append({"icon": "🌊", "title": "Flat Ride", "detail": f"Only {act.elevation_gain_m:.0f}m over {act.distance_m/1000:.0f}km -- pancake flat."})

    # 3. Zone distribution from power stream
    if act.streams:
        try:
            s = act.streams
            if isinstance(s, str): s = json.loads(s)
            pw = None
            if "watts" in s:
                w = s["watts"]
                pw = w["data"] if isinstance(w, dict) and "data" in w else (w if isinstance(w, list) else None)
            elif "power" in s:
                p = s["power"]
                pw = p["data"] if isinstance(p, dict) and "data" in p else (p if isinstance(p, list) else None)
            if pw:
                clean = [x for x in pw if x is not None and x > 0]
                if clean:
                    ftp = 236
                    zones = {1:0,2:0,3:0,4:0,5:0,6:0,7:0}
                    for w in clean:
                        pct = w / ftp * 100
                        if pct < 55: zones[1] += 1
                        elif pct < 75: zones[2] += 1
                        elif pct < 90: zones[3] += 1
                        elif pct < 105: zones[4] += 1
                        elif pct < 120: zones[5] += 1
                        elif pct < 150: zones[6] += 1
                        else: zones[7] += 1
                    total_z = sum(zones.values())
                    if total_z > 0:
                        top_zone = max(zones, key=zones.get)
                        top_pct = zones[top_zone] / total_z * 100
                        zone_names = {1:"Recovery",2:"Endurance",3:"Tempo",4:"Threshold",5:"VO2Max",6:"Anaerobic",7:"Neuromuscular"}
                        if top_pct > 40:
                            act_insights.append({"icon": "📊", "title": f"Primarily Z{top_zone} ({zone_names[top_zone]})", "detail": f"{top_pct:.0f}% of riding was in Z{top_zone} -- a {zone_names[top_zone].lower()}-focused session."})
                        # Check for high intensity
                        z5_7 = zones[5] + zones[6] + zones[7]
                        if z5_7 / total_z > 0.15:
                            act_insights.append({"icon": "💥", "title": "High Intensity Session", "detail": f"{(z5_7/total_z*100):.0f}% of time above Z4 -- significant anaerobic work."})
                        elif zones[2] / total_z > 0.6:
                            act_insights.append({"icon": "🚴", "title": "Endurance Focus", "detail": f"{(zones[2]/total_z*100):.0f}% in Z2 -- solid aerobic base ride."})
        except: pass

    # 4. Training load
    if act.tss:
        if act.tss > 200:
            act_insights.append({"icon": "💪", "title": "High Training Stress", "detail": f"TSS of {act.tss:.0f} -- a significant training load. Ensure adequate recovery."})
        elif act.tss < 50:
            act_insights.append({"icon": "🌿", "title": "Light Effort", "detail": f"TSS of {act.tss:.0f} -- a recovery or easy day."})

    # 5. Caloric impact
    if act.calories_kcal and act.calories_kcal > 2000:
        act_insights.append({"icon": "🔥", "title": "High Calorie Burn", "detail": f"{act.calories_kcal:.0f} kcal burned -- refuel well."})

    if not act_insights:
        act_insights.append({"icon": "📝", "title": "Limited Data", "detail": "No power or GPS data available for detailed analysis."})

    return {"insights": act_insights, "count": len(act_insights)}
