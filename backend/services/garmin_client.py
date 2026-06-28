"""Garmin Connect API client."""
import os, json, logging
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    from garminconnect import Garmin
    HAS_GARMIN = True
except ImportError:
    HAS_GARMIN = False


def is_available():
    return HAS_GARMIN


def is_configured():
    email = os.getenv("GARMIN_EMAIL", "")
    password = os.getenv("GARMIN_PASSWORD", "")
    return bool(email and password)


def get_credentials():
    return {
        "email": os.getenv("GARMIN_EMAIL", ""),
        "password": os.getenv("GARMIN_PASSWORD", ""),
    }


def create_client(email=None, password=None):
    if not HAS_GARMIN:
        raise ImportError("garminconnect library not installed")
    creds = get_credentials()
    email = email or creds["email"]
    password = password or creds["password"]
    if not email or not password:
        raise ValueError("Garmin email and password required")
    client = Garmin(email, password)
    client.login()
    logger.info(f"Logged into Garmin Connect as {email}")
    return client


def list_activities(client, start=0, limit=20):
    return client.get_activities(start, limit)


def get_activity_data(client, activity_id):
    try:
        return client.get_activity(activity_id)
    except Exception as e:
        logger.warning(f"Failed to get activity {activity_id}: {e}")
        return None


def download_activity(client, activity_id):
    try:
        data = client.download_activity(activity_id, dl_fmt=client.ActivityDownloadFormat.FIT)
        if data:
            return data, f"garmin_{activity_id}.fit"
        return None, None
    except Exception as e:
        logger.warning(f"Failed to download activity {activity_id}: {e}")
        return None, None


def get_health_data(client, date=None):
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    try:
        return {
            "hrv": client.get_hrv_data(date),
            "sleep": client.get_sleep_data(date),
            "heart_rate": client.get_heart_rates(date),
            "steps": client.get_steps_data(date),
            "body_composition": client.get_body_composition(date),
            "stress": client.get_stress_data(date),
            "spo2": client.get_spo2_data(date),
        }
    except Exception as e:
        logger.warning(f"Failed to get health data for {date}: {e}")
        return {}


def get_stats(client):
    try:
        return client.get_stats()
    except Exception as e:
        return {}


def get_weight_data(client, date=None):
    """Get weight and body composition data via the weight service endpoint."""
    from datetime import datetime, timedelta
    import json, logging
    logger = logging.getLogger(__name__)
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    # Get a range around the date to make sure we capture it
    start = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    end = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        data = client.connectapi(f"/weight-service/weight/range/{start}/{end}")
        if isinstance(data, dict):
            logger.info(f"Weight API keys: {list(data.keys())}")
            summaries = data.get("dailyWeightSummaries", [])
            logger.info(f"Weight summaries count: {len(summaries)}")
            if summaries:
                for s in summaries:
                    sd = s.get("summaryDate")
                    logger.info(f"  Summary date: {sd}, looking for: {date}, match: {sd == date}")
                    if sd == date:
                        lw = s.get("latestWeight", {})
                        logger.info(f"  Found! bodyFat={lw.get(chr(98)+chr(111)+chr(100)+chr(121)+chr(70)+chr(97)+chr(116))}")
                        return lw
                lw = summaries[0].get("latestWeight", {})
                logger.info(f"  Using first, bodyFat={lw.get(chr(98)+chr(111)+chr(100)+chr(121)+chr(70)+chr(97)+chr(116))}")
                return lw
        return {}
    except Exception as e:
        logger.warning(f"Failed to get weight data: {e}")
        return {}
