"""Wahoo auto-sync service — polls for new workouts, downloads files, imports into CycleStats.

Architecture:
  1. Background polling via cron job or API trigger
  2. Checks Wahoo API for workouts updated since last_sync_at
  3. Downloads FIT/GPX/TCX files for new workouts
  4. Parses and imports into the Activity table
  5. Tracks imported workout IDs in WahooWorkout table to prevent dupes
"""
import os
import io
import re
import logging
import tempfile
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from database import WahooAccount, WahooWorkout, Activity, init_db
from services import wahoo_client
from services.file_parser import parse_activity_file

logger = logging.getLogger(__name__)

# Import directory for downloaded files
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "wahoo_downloads")


def sync_all_accounts(db: Session):
    """Sync all active Wahoo accounts. Called by the cron job or API trigger."""
    accounts = db.query(WahooAccount).filter(
        WahooAccount.is_active == 1,
        WahooAccount.sync_enabled == 1,
    ).all()

    results = []
    for account in accounts:
        try:
            result = sync_account(account, db)
            results.append({
                "account_id": account.id,
                "email": account.email,
                "new_workouts": result["new_workouts"],
                "errors": result["errors"],
            })
        except Exception as e:
            logger.exception(f"Sync failed for account {account.id}")
            results.append({
                "account_id": account.id,
                "email": account.email,
                "error": str(e),
            })

    return results


def sync_account(account: WahooAccount, db: Session):
    """Sync a single Wahoo account — fetch new workouts and import them.

    Returns dict with new_workouts count and any errors.
    """
    if not account.is_active or not account.sync_enabled:
        return {"new_workouts": 0, "errors": []}

    # Refresh token if needed
    token = _ensure_valid_token(account, db)
    if not token:
        account.is_active = 0
        db.commit()
        return {"new_workouts": 0, "errors": ["Token invalid, account deactivated"]}

    # Determine the last sync timestamp (ISO format for API)
    last_sync = account.last_sync_at
    if last_sync and last_sync.tzinfo is None:
        last_sync = last_sync.replace(tzinfo=timezone.utc)

    updated_after = last_sync.isoformat() if last_sync else None
    # If never synced, get workouts from the last 7 days
    if not updated_after:
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        updated_after = seven_days_ago.isoformat()

    new_count = 0
    errors = []
    page = 1
    total_pages = 1

    while page <= total_pages:
        try:
            data = wahoo_client.list_workouts(
                token,
                page=page,
                per_page=50,
                updated_after=updated_after,
            )
        except Exception as e:
            logger.error(f"Failed to list workouts (page {page}): {e}")
            errors.append(f"Page {page}: {str(e)}")
            break

        workouts = data.get("workouts", [])
        total = data.get("total", 0)
        per_page = data.get("per_page", 50)
        total_pages = max(1, (total + per_page - 1) // per_page) if total > 0 else 1

        for w in workouts:
            w_id = w.get("id")
            if not w_id:
                continue

            # Check if already imported
            existing = db.query(WahooWorkout).filter(
                WahooWorkout.wahoo_workout_id == w_id,
                WahooWorkout.wahoo_account_id == account.id,
            ).first()

            if existing:
                continue

            # Skip workouts without file data
            if not w.get("has_file", True):
                logger.info(f"Skipping workout {w_id} — no file available")
                # Still mark as seen so we don't retry
                _mark_seen(w_id, account.id, db, None)
                continue

            # Download and import
            try:
                activity_id = _import_workout(w, token, account.id, db)
                if activity_id:
                    new_count += 1
                    logger.info(f"Imported Wahoo workout {w_id} → activity {activity_id}")
            except Exception as e:
                logger.exception(f"Failed to import workout {w_id}: {e}")
                errors.append(f"Workout {w_id}: {str(e)}")
                # Still mark as seen to avoid retry spam
                _mark_seen(w_id, account.id, db, None)

        page += 1

    # Update last sync time
    account.last_sync_at = datetime.utcnow()
    db.commit()

    return {"new_workouts": new_count, "errors": errors}


def _ensure_valid_token(account: WahooAccount, db: Session):
    """Check if token is expired and refresh if needed. Returns a valid access token."""
    if not account.access_token:
        return None

    now = datetime.utcnow()
    expires_at = account.token_expires_at

    # If token is still valid (with 5 min buffer), use it
    if expires_at and expires_at > now + timedelta(minutes=5):
        return account.access_token

    # Need to refresh
    if not account.refresh_token:
        logger.error(f"No refresh token for account {account.id}")
        return None

    try:
        result = wahoo_client.refresh_access_token(account.refresh_token)
        account.access_token = result["access_token"]
        account.refresh_token = result.get("refresh_token", account.refresh_token)
        expires_in = result.get("expires_in", 7200)
        account.token_expires_at = now + timedelta(seconds=expires_in)
        db.commit()
        logger.info(f"Refreshed token for account {account.id}")
        return account.access_token
    except Exception as e:
        logger.error(f"Token refresh failed for account {account.id}: {e}")
        return None


def _import_workout(workout_data, access_token, account_id, db: Session):
    """Download a Wahoo workout file and import into CycleStats.

    Returns the new Activity ID, or None on failure.
    """
    w_id = workout_data["id"]

    # Try to download the FIT file
    file_bytes = None
    ext = None
    
    # First, check workout_summary for file URL
    ws = workout_data.get("workout_summary", {}) or {}
    file_info = ws.get("file", {}) or {}
    file_url = file_info.get("url", "")
    
    if file_url:
        try:
            raw = wahoo_client._api_download_file(file_url, access_token)
            if raw:
                file_bytes = raw
                ext = ".fit"
                logger.info(f"Downloaded FIT from summary URL for workout {w_id}")
        except Exception as e:
            logger.warning(f"Could not download from summary URL: {e}")
            # Try without auth (CDN might reject Bearer token)
            try:
                import urllib.request
                req = urllib.request.Request(file_url)
                with urllib.request.urlopen(req, timeout=60) as resp:
                    raw = resp.read()
                if raw:
                    file_bytes = raw
                    ext = ".fit"
                    logger.info(f"Downloaded FIT from summary URL (no auth) for workout {w_id}")
            except Exception as e2:
                logger.warning(f"Also failed without auth: {e2}")
    
    # Fallback: try the /file endpoint
    if not file_bytes:
        try:
            file_bytes, ext = wahoo_client.download_workout_file(w_id, access_token)
        except Exception as e:
            logger.warning(f"Could not download file for workout {w_id}: {e}")
    
    if not file_bytes:
        return _import_from_minimal(workout_data, account_id, db)

    # Save to temp file and parse
    safe_name = f"wahoo_{w_id}{ext}"
    os.makedirs(DATA_DIR, exist_ok=True)
    filepath = os.path.join(DATA_DIR, safe_name)

    try:
        with open(filepath, "wb") as f:
            f.write(file_bytes)
    except Exception as e:
        logger.error(f"Failed to save file {filepath}: {e}")
        return None

    # Parse file
    try:
        parsed = parse_activity_file(filepath)
    except Exception as e:
        logger.error(f"Failed to parse downloaded file {filepath}: {e}")
        return _import_from_minimal(workout_data, account_id, db)

    if not parsed or not parsed.get("start_time"):
        return _import_from_minimal(workout_data, account_id, db)

    # Create activity record
    start_time = parsed["start_time"]
    if isinstance(start_time, str):
        try:
            start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except ValueError:
            start_time = datetime.utcnow()

    activity = Activity(
        name=ws.get("name") or parsed.get("name") or workout_data.get("name") or f"Wahoo {w_id}",
        sport=parsed.get("sport", "cycling"),
        start_time=start_time,
        end_time=parsed.get("end_time", start_time),
        source_file=filepath,
        file_format=parsed.get("file_format", ext.lstrip(".")),
        distance_m=parsed.get("distance_m", 0),
        moving_time_s=parsed.get("moving_time_s", 0),
        elapsed_time_s=parsed.get("elapsed_time_s", 0),
        avg_speed_ms=parsed.get("avg_speed_ms", 0),
        max_speed_ms=parsed.get("max_speed_ms", 0),
        elevation_gain_m=parsed.get("elevation_gain_m", 0),
        elevation_loss_m=parsed.get("elevation_loss_m", 0),
        avg_elevation_m=parsed.get("avg_elevation_m"),
        max_elevation_m=parsed.get("max_elevation_m"),
        min_elevation_m=parsed.get("min_elevation_m"),
        avg_heartrate=parsed.get("avg_heartrate"),
        max_heartrate=parsed.get("max_heartrate"),
        avg_power_w=parsed.get("avg_power_w"),
        max_power_w=parsed.get("max_power_w"),
        normalized_power_w=parsed.get("normalized_power_w"),
        avg_cadence=parsed.get("avg_cadence"),
        max_cadence=parsed.get("max_cadence"),
        calories_kcal=parsed.get("calories_kcal"),
        kilojoules_kj=parsed.get("kilojoules_kj"),
        intensity_factor=parsed.get("intensity_factor"),
        track_geojson=parsed.get("track_geojson"),
        streams=parsed.get("streams"),
    )

    # Compute NP if available in streams
    if not activity.normalized_power_w and activity.streams and "power" in activity.streams:
        powers = [p for p in activity.streams["power"] if p is not None]
        if len(powers) >= 30:
            from services.file_parser import _normalized_power
            activity.normalized_power_w = _normalized_power(powers)

    db.add(activity)
    db.flush()  # Get activity.id

    # Mark as imported
    _mark_seen(w_id, account_id, db, activity.id)

    return activity.id


def _import_from_minimal(workout_data, account_id, db: Session):
    """Create a minimal activity entry from Wahoo metadata when no file is available."""
    w_id = workout_data["id"]
    ws = workout_data.get("workout_summary", {}) or {}
    name = ws.get("name") or workout_data.get("name", f"Wahoo {w_id}")
    start_str = ws.get("started_at") or workout_data.get("start", workout_data.get("start_time", workout_data.get("starts")))
    start_time = datetime.utcnow()
    if start_str:
        try:
            start_time = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        except ValueError:
            pass

    duration_s = float(ws.get("duration_active_accum", 0)) or float(ws.get("duration_total_accum", 0)) or 0
    distance_m = float(ws.get("distance_accum", 0)) or float(ws.get("distance", 0)) or float(workout_data.get("distance", 0))
    if not distance_m:
        return None

    # Extract additional metrics from workout_summary
    avg_power = _safe_float(ws.get("power_avg"))
    avg_hr = _safe_float(ws.get("heart_rate_avg"))
    elevation = _safe_float(ws.get("ascent_accum"))
    avg_cadence = _safe_float(ws.get("cadence_avg"))
    calories = _safe_float(ws.get("calories_accum"))
    avg_speed = _safe_float(ws.get("speed_avg"))
    work = _safe_float(ws.get("work_accum"))
    np = _safe_float(ws.get("power_bike_np_last"))
    tss = _safe_float(ws.get("power_bike_tss_last"))

    activity = Activity(
        name=name,
        sport="cycling",
        start_time=start_time,
        end_time=start_time + timedelta(seconds=duration_s) if duration_s else start_time,
        distance_m=distance_m,
        moving_time_s=duration_s,
        elapsed_time_s=duration_s,
        avg_power_w=avg_power,
        max_power_w=None,
        normalized_power_w=np,
        avg_heartrate=avg_hr,
        max_heartrate=None,
        avg_cadence=avg_cadence,
        avg_speed_ms=avg_speed,
        elevation_gain_m=elevation,
        calories_kcal=calories or None,
        kilojoules_kj=work,
        tss=tss,
        source_file=f"wahoo://workout/{w_id}",
    )
    db.add(activity)
    db.flush()

    _mark_seen(w_id, account_id, db, activity.id)
    return activity.id





def _safe_float(val):
    """Safely convert a value to float, returning None on failure."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None

def _mark_seen(wahoo_workout_id, account_id, db, activity_id):
    """Record that a Wahoo workout has been processed."""
    existing = db.query(WahooWorkout).filter(
        WahooWorkout.wahoo_workout_id == wahoo_workout_id,
        WahooWorkout.wahoo_account_id == account_id,
    ).first()

    if not existing:
        record = WahooWorkout(
            wahoo_workout_id=wahoo_workout_id,
            wahoo_account_id=account_id,
            activity_id=activity_id,
            imported_at=datetime.utcnow(),
        )
        db.add(record)
        db.commit()


def get_sync_status(db: Session):
    """Get sync status for all connected Wahoo accounts."""
    accounts = db.query(WahooAccount).filter(WahooAccount.is_active == 1).all()
    return [a.to_dict() for a in accounts]


def disconnect_account(account_id, db: Session):
    """Disconnect a Wahoo account and revoke tokens."""
    account = db.query(WahooAccount).filter(WahooAccount.id == account_id).first()
    if not account:
        return False

    # Try to revoke tokens at Wahoo
    try:
        token = _ensure_valid_token(account, db)
        if token:
            import urllib.request
            req = urllib.request.Request(
                f"{wahoo_client.API_BASE}/v1/permissions",
                method="DELETE",
                headers={"Authorization": f"Bearer {token}"},
            )
            urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass  # Best effort

    # Remove tracking records
    db.query(WahooWorkout).filter(WahooWorkout.wahoo_account_id == account_id).delete()
    db.delete(account)
    db.commit()
    return True
