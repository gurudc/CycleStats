"""Wahoo Cloud API client — OAuth2, token management, workout fetching, file download."""
import os, json, time, secrets, logging, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from services.tunnel import get_redirect_uri, start_tunnel

logger = logging.getLogger(__name__)

API_BASE = "https://api.wahooligan.com"
AUTH_URL = f"{API_BASE}/oauth/authorize"
TOKEN_URL = f"{API_BASE}/oauth/token"

REQUIRED_SCOPES = ["user_read", "workouts_read", "offline_data"]


def get_config():
    return {
        "client_id": os.getenv("WAHOO_CLIENT_ID", ""),
        "client_secret": os.getenv("WAHOO_CLIENT_SECRET", ""),
        "redirect_uri": os.getenv("WAHOO_REDIRECT_URI", "http://127.0.0.1:8080/api/wahoo/callback"),
    }


def is_configured():
    cfg = get_config()
    return bool(cfg["client_id"] and cfg["client_secret"])



def build_auth_url(redirect_uri=None):
    cfg = get_config()
    redirect = redirect_uri or get_redirect_uri()
    if not redirect_uri and "http://127.0.0.1" in redirect and "https://" not in redirect:
        tunnel_url = start_tunnel()
        if tunnel_url:
            redirect = f"{tunnel_url}/api/wahoo/callback"
            os.environ["TUNNEL_REDIRECT_URI"] = redirect
            logger.info(f"Using HTTPS tunnel redirect: {redirect}")
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": redirect,
        "scope": " ".join(REQUIRED_SCOPES),
        "response_type": "code",
    }
    url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    return url, None, None, redirect


def exchange_code(code, code_verifier=None, redirect_uri=None):
    cfg = get_config()
    redirect = redirect_uri or cfg["redirect_uri"]
    data = {
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "redirect_uri": redirect,
        "grant_type": "authorization_code",
        "code": code,
    }
    return _post_token(data)


def refresh_access_token(refresh_token):
    cfg = get_config()
    data = {
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    return _post_token(data)


def _post_token(data):
    payload = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(TOKEN_URL, data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise Exception(f"Wahoo token error ({e.code}): {body}")


def _api_get(path, access_token, params=None):
    url = f"{API_BASE}{path}"
    if params:
        url += f"?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {access_token}", "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        if e.code == 401:
            raise PermissionError(f"Token expired or invalid: {body}")
        raise Exception(f"Wahoo API error ({e.code}): {body}")


def _api_download_file(url, access_token):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read()
    except Exception as e:
        raise


def get_user_info(access_token):
    return _api_get("/v1/user", access_token)


def list_workouts(access_token, page=1, per_page=50, updated_after=None):
    params = {"page": page, "per_page": min(per_page, 50)}
    if updated_after:
        params["updated_after"] = updated_after
    return _api_get("/v1/workouts", access_token, params)


def get_workout_file_info(workout_id, access_token):
    return _api_get(f"/v1/workouts/{workout_id}/file", access_token)


def download_workout_file(workout_id, access_token):
    file_info = get_workout_file_info(workout_id, access_token)
    file_url = file_info.get("file", {}).get("url") or file_info.get("url")
    if not file_url:
        return None, None
    ext = ".fit"
    for e in [".fit", ".gpx", ".tcx", ".json"]:
        if e in file_url.lower():
            ext = e
            break
    fmt = file_info.get("file", {}).get("format", "").lower()
    if fmt == "fit": ext = ".fit"
    elif fmt in ("gpx", "tcx"): ext = f".{fmt}"
    raw = _api_download_file(file_url, access_token)
    return raw, ext


def parse_workout_data(raw_workout):
    return {
        "id": raw_workout.get("id"),
        "name": raw_workout.get("name", "Wahoo Workout"),
        "start_time": raw_workout.get("start"),
        "end_time": raw_workout.get("stop"),
        "sport": raw_workout.get("workout_type", raw_workout.get("sport", "cycling")).lower(),
        "distance_m": raw_workout.get("distance", 0),
        "duration_s": raw_workout.get("duration", 0),
        "calories_kcal": raw_workout.get("calories"),
        "has_file": raw_workout.get("has_file", False),
        "updated_at": raw_workout.get("updated_at"),
    }


def get_workout(workout_id, access_token):
    """Get detailed workout data including samples."""
    return _api_get(f"/v1/workouts/{workout_id}", access_token)


def get_workout_samples(workout_id, access_token):
    """Get time-series samples for a workout."""
    try:
        return _api_get(f"/v1/workouts/{workout_id}/samples", access_token)
    except Exception as e:
        return None
