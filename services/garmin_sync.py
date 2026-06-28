"""Garmin auto-sync service."""
import os, json, logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from database import Activity, HealthCheckin
from services import garmin_client
from services.file_parser import parse_activity_file

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "garmin_downloads")
STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "garmin_state.json")


def _state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_id": 0, "last_sync": None}


def _save(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def sync_all(db: Session):
    if not garmin_client.is_configured():
        return {"error": "Garmin credentials not set. Add GARMIN_EMAIL and GARMIN_PASSWORD to .env"}

    try:
        client = garmin_client.create_client()
    except Exception as e:
        return {"error": f"Garmin login failed: {str(e)}"}

    state = _state()
    last_id = state.get("last_id", 0)
    new_count = 0
    errors = []
    newest_id = last_id

    start = 0
    while start < 100:
        try:
            activities = garmin_client.list_activities(client, start, 20)
        except Exception as e:
            errors.append(f"List failed: {e}")
            break

        if not activities:
            break

        for act in activities:
            aid = act.get("activityId") or act.get("activity_id")
            if not aid:
                continue
            if aid <= last_id:
                start = 100
                break

            try:
                result = _import(act, client, db)
                if result:
                    new_count += 1
            except Exception as e:
                errors.append(f"Activity {aid}: {e}")

            if aid > newest_id:
                newest_id = aid

        start += 20

    state["last_id"] = newest_id
    state["last_sync"] = datetime.utcnow().isoformat()
    _save(state)

    health_count = 0
    try:
        health_count = _sync_health(client, db)
    except Exception as e:
        logger.warning(f"Health sync: {e}")

    return {"new_activities": new_count, "health_records": health_count, "errors": errors}


def _import(act, client, db):
    aid = act.get("activityId") or act.get("activity_id")
    # Skip if no distance
    if not act.get("distance", 0):
        return None
    file_bytes, filename = garmin_client.download_activity(client, aid)
    if file_bytes:
        os.makedirs(DATA_DIR, exist_ok=True)
        fp = os.path.join(DATA_DIR, filename)
        with open(fp, "wb") as f:
            f.write(file_bytes)
        try:
            parsed = parse_activity_file(fp)
            if parsed and parsed.get("start_time"):
                return _make_activity(parsed, act, fp, db)
        except Exception:
            pass
    return _from_meta(act, db)


def _make_activity(parsed, act, filepath, db):
    st = parsed["start_time"]
    if isinstance(st, str):
        try:
            st = datetime.fromisoformat(st.replace("Z", "+00:00"))
        except ValueError:
            st = datetime.utcnow()

    activity = Activity(
        name=parsed.get("name", act.get("activityName", "Garmin Activity")),
        sport=_sport(act),
        start_time=st,
        end_time=parsed.get("end_time", st),
        source_file=filepath,
        file_format=parsed.get("file_format", "fit"),
        distance_m=parsed.get("distance_m", 0),
        moving_time_s=parsed.get("moving_time_s", 0),
        elapsed_time_s=parsed.get("elapsed_time_s", 0),
        avg_speed_ms=parsed.get("avg_speed_ms", 0),
        max_speed_ms=parsed.get("max_speed_ms", 0),
        elevation_gain_m=parsed.get("elevation_gain_m", 0),
        avg_heartrate=parsed.get("avg_heartrate"),
        max_heartrate=parsed.get("max_heartrate"),
        avg_power_w=parsed.get("avg_power_w"),
        max_power_w=parsed.get("max_power_w"),
        normalized_power_w=parsed.get("normalized_power_w"),
        avg_cadence=parsed.get("avg_cadence"),
        calories_kcal=parsed.get("calories_kcal"),
        kilojoules_kj=parsed.get("kilojoules_kj"),
        track_geojson=parsed.get("track_geojson"),
        streams=parsed.get("streams"),
    )
    if not activity.normalized_power_w and activity.streams:
        pws = [p for p in activity.streams.get("power", []) if p is not None]
        if len(pws) >= 30:
            from services.file_parser import _normalized_power
            activity.normalized_power_w = _normalized_power(pws)
    db.add(activity)
    db.commit()
    return activity


def _from_meta(act, db):
    aid = act.get("activityId") or act.get("activity_id")
    if not act.get("distance", 0):
        return None
    start_str = act.get("startTimeLocal", act.get("start_time"))
    st = datetime.utcnow()
    if start_str:
        try:
            st = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        except ValueError:
            pass

    activity = Activity(
        name=act.get("activityName", f"Garmin {aid}"),
        sport=_sport(act),
        start_time=st,
        distance_m=act.get("distance", 0),
        moving_time_s=act.get("duration", 0),
        elapsed_time_s=act.get("duration", 0),
        avg_heartrate=act.get("averageHeartRate", act.get("avg_heart_rate")),
        avg_power_w=act.get("averagePower", act.get("avg_power")),
        calories_kcal=act.get("calories"),
        elevation_gain_m=act.get("elevationGain", act.get("elevation_gain", 0)),
        source_file=f"garmin://activity/{aid}",
    )
    db.add(activity)
    db.commit()
    return activity


def _sync_health(client, db):
    count = 0
    for off in range(14):
        date = (datetime.utcnow() - timedelta(days=off)).strftime("%Y-%m-%d")
        try:
            h = garmin_client.get_health_data(client, date)
            if not h:
                continue
            cd = datetime.strptime(date, "%Y-%m-%d")
            exist = db.query(HealthCheckin).filter(
                HealthCheckin.date >= cd,
                HealthCheckin.date < cd + timedelta(days=1)
            ).first()

            hrv_d = h.get("hrv", {}) or {}
            sleep_d = h.get("sleep", {}) or {}
            hr_d = h.get("heart_rate", {}) or {}
            steps_d = h.get("steps", {}) or {}
            body_d = h.get("body_composition", {}) or {}
            weight_data = {}
            try:
                wd = garmin_client.get_weight_data(client, date)
                if wd:
                    weight_data = wd
            except Exception:
                pass

            data = {
                "date": datetime.strptime(date, "%Y-%m-%d"),
                "resting_hr": hr_d.get("restingHeartRate") if isinstance(hr_d, dict) else None,
                "hrv_rmssd": (hrv_d.get("hrvSummary") or {}).get("lastNightAvg") or (hrv_d.get("hrvSummary") or {}).get("weeklyAvg") if isinstance(hrv_d, dict) else None,
                "sleep_hours": None,
                "sleep_score": None,
                "steps": steps_d.get("totalSteps") if isinstance(steps_d, dict) else None,
                "weight_kg": (weight_data.get("weight") / 1000) if weight_data.get("weight") else body_d.get("weight") or (body_d.get("totalAverage") or {}).get("weight") if isinstance(body_d, dict) else None,
            "body_fat_pct": weight_data.get("bodyFat") if weight_data.get("bodyFat") is not None else (body_d.get("bodyFat") if isinstance(body_d, dict) else None),
            }

            if isinstance(sleep_d, dict):
                sd = sleep_d.get("dailySleepDTO", {})
                secs = sd.get("sleepTimeSeconds")
                if secs:
                    data["sleep_hours"] = round(secs / 3600, 1)
                sc = sd.get("sleepScores", {}).get("overall", {}).get("value")
                if sc:
                    data["sleep_score"] = sc

            if exist:
                for k, v in data.items():
                    if v is not None and hasattr(exist, k):
                        setattr(exist, k, v)
            else:
                clean = {k: v for k, v in data.items() if v is not None}
                if len(clean) > 1:
                    db.add(HealthCheckin(**clean))
            count += 1
        except Exception as e:
            logger.warning(f"Health {date}: {e}")
    db.commit()
    return count



def sync_health_only(db):
    """Only sync health data from Garmin, skip activities."""
    if not garmin_client.is_configured():
        return {"error": "Garmin credentials not set"}
    try:
        client = garmin_client.create_client()
    except Exception as e:
        return {"error": "Garmin login failed: " + str(e)}
    try:
        count = _sync_health(client, db)
        return {"health_records": count, "errors": []}
    except Exception as e:
        return {"error": str(e), "health_records": 0, "errors": [str(e)]}


def _sport(act):
    t = act.get("activityType", {})
    if isinstance(t, dict):
        key = t.get("typeKey", "")
    else:
        key = act.get("activityType", "")
    m = {
        "cycling": "cycling", "biking": "cycling", "road_biking": "cycling",
        "mountain_biking": "cycling", "gravel_cycling": "cycling", "virtual_ride": "cycling",
        "running": "running", "trail_running": "running", "treadmill_running": "running",
        "swimming": "swimming", "walking": "walking", "hiking": "hiking",
        "strength_training": "strength", "cardio": "cardio", "yoga": "yoga",
    }
    return m.get(key, key or "cycling")
