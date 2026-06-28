"""Activity upload, list, detail, delete endpoints."""
import os
import json
import shutil
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from database import get_db, Activity, init_db
from routers.auth import require_session
from services.file_parser import parse_activity_file
from services.power_duration import compute_activity_power_duration, compute_xss, compute_tss
from services.training_load import update_training_load

router = APIRouter(prefix="/api/activities", tags=["activities"])
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "activities"
DATA_DIR.mkdir(parents=True, exist_ok=True)


from schemas.activity import ActivityRead
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, Query
from typing import List

router = APIRouter(prefix="/api/activities", tags=["activities"])

@router.get("/", response_model=dict)
def list_activities(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sport: str = None,
    q: str = None,
    date_from: str = None,
    date_to: str = None,
        _session = Depends(require_session)):
    """List activities with pagination, search, and filters."""
    query = db.query(Activity).order_by(desc(Activity.start_time))
    if sport:
        query = query.filter(Activity.sport == sport)
    if q:
        query = query.filter(Activity.name.ilike(f"%{q}%"))
    if date_from:
        from datetime import datetime
        query = query.filter(Activity.start_time >= datetime.fromisoformat(date_from))
    if date_to:
        from datetime import datetime, timedelta
        query = query.filter(Activity.start_time < datetime.fromisoformat(date_to) + timedelta(days=1))
    total = query.count()
    activities = query.offset(offset).limit(limit).all()
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "activities": [ActivityRead.from_orm(a).dict() for a in activities],
    }


@router.get("/{activity_id}")
def get_activity(activity_id: int, db: Session = Depends(get_db), streams: bool = False,         _session = Depends(require_session)):
    """Get a single activity with optional streams."""
    activity = db.query(Activity).filter(Activity.id == activity_id).first()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
    result = activity.to_dict(include_streams=streams)
    try:
        from services.hr_analysis import compute_hr_metrics
        s = activity.streams
        if s and isinstance(s, dict) and "heartrate" in s:
            hr_m = compute_hr_metrics(s)
            result["hr_metrics"] = hr_m if hr_m else None
    except Exception:
        result["hr_metrics"] = None
    return result


@router.patch("/{activity_id}/notes")
def update_activity_notes(activity_id: int, body: dict, db: Session = Depends(get_db), _session=Depends(require_session)):
    """Update notes/tags for an activity."""
    activity = db.query(Activity).filter(Activity.id == activity_id).first()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
    activity.notes = body.get("notes", "")
    db.commit()
    return {"success": True, "notes": activity.notes}

@router.get("/export/{fmt}")
def export_activities(fmt: str = "json", limit: int = 5000, offset: int = 0, db: Session = Depends(get_db),         _session = Depends(require_session)):
    """Export activities as CSV or JSON."""
    from fastapi.responses import PlainTextResponse
    import csv, io
    
    activities = db.query(Activity).order_by(Activity.start_time.desc()).offset(offset).limit(limit).all()
    
    if fmt == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id","name","date","sport","distance_km","duration_h","avg_power_w","max_power_w","normalized_power_w","avg_hr","max_hr","avg_cadence","elevation_m","tss","if","calories","notes"])
        for a in activities:
            writer.writerow([
                a.id, a.name, str(a.start_time)[:10] if a.start_time else "",
                a.sport, round((a.distance_m or 0)/1000, 2), round((a.moving_time_s or 0)/3600, 2),
                a.avg_power_w, a.max_power_w, a.normalized_power_w,
                a.avg_heartrate, a.max_heartrate, a.avg_cadence,
                a.elevation_gain_m, a.tss, a.intensity_factor, a.calories_kcal, a.notes or ""
            ])
        return PlainTextResponse(output.getvalue(), media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=cyclestats_activities.csv"})
    
    result = []
    for a in activities:
        d = a.to_dict()
        result.append(d)
    return result

@router.post("/upload")
async def upload_activity(
    file: UploadFile = File(...),
    name: str = Form(None),
    sport: str = Form(None),
    db: Session = Depends(get_db),
    ftp: float = Form(None),
        _session = Depends(require_session)):
    """Upload a FIT, GPX, or TCX file and parse it."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".fit", ".gpx", ".tcx"):
        raise HTTPException(status_code=400, detail=f"Unsupported format: {ext}")

    # Save file
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_name = f"{timestamp}_{file.filename}"
    filepath = DATA_DIR / safe_name

    with open(filepath, "wb") as f:
        content = await file.read()
        f.write(content)

    # Parse
    try:
        result = parse_activity_file(str(filepath))
    except Exception as e:
        logger.exception(f"Failed to parse {filepath}")
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {str(e)}")

    if not result or not result.get("start_time"):
        raise HTTPException(status_code=400, detail="Could not extract any data from file")

    # Override fields
    if name:
        result["name"] = name
    if sport:
        result["sport"] = sport

    # Convert times
    start_time = result["start_time"]
    if isinstance(start_time, str):
        try:
            start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except ValueError:
            start_time = datetime.utcnow()

    end_time = result.get("end_time", start_time)
    if isinstance(end_time, str):
        try:
            end_time = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        except ValueError:
            end_time = start_time

    # Create activity record
    activity = Activity(
        name=result.get("name", file.filename),
        sport=result.get("sport", "cycling"),
        start_time=start_time,
        end_time=end_time,
        source_file=str(filepath),
        file_format=result.get("file_format", ext[1:]),
        distance_m=result.get("distance_m", 0),
        moving_time_s=result.get("moving_time_s", result.get("elapsed_time_s", 0)),
        elapsed_time_s=result.get("elapsed_time_s", 0),
        avg_speed_ms=result.get("avg_speed_ms", 0),
        max_speed_ms=result.get("max_speed_ms", 0),
        elevation_gain_m=result.get("elevation_gain_m", 0),
        elevation_loss_m=result.get("elevation_loss_m", 0),
        avg_elevation_m=result.get("avg_elevation_m"),
        max_elevation_m=result.get("max_elevation_m"),
        min_elevation_m=result.get("min_elevation_m"),
        avg_heartrate=result.get("avg_heartrate"),
        max_heartrate=result.get("max_heartrate"),
        avg_power_w=result.get("avg_power_w"),
        max_power_w=result.get("max_power_w"),
        normalized_power_w=result.get("normalized_power_w"),
        avg_cadence=result.get("avg_cadence"),
        max_cadence=result.get("max_cadence"),
        calories_kcal=result.get("calories_kcal"),
        kilojoules_kj=result.get("kilojoules_kj"),
        intensity_factor=result.get("intensity_factor"),
        track_geojson=result.get("track_geojson"),
        laps=result.get("laps"),
        streams=result.get("streams"),
    )

    # Compute NP if not already set
    if not activity.normalized_power_w and activity.streams and "power" in activity.streams:
        powers = [p for p in activity.streams["power"] if p is not None]
        if len(powers) >= 30:
            from services.file_parser import _normalized_power
            activity.normalized_power_w = _normalized_power(powers)

    # Compute TSS if we have FTP
    if ftp and activity.normalized_power_w:
        activity.tss = compute_tss(
            activity.streams.get("power", []) if activity.streams else [],
            activity.normalized_power_w,
            ftp,
            (activity.moving_time_s or activity.elapsed_time_s or 3600) / 3600,
        )
        if activity.normalized_power_w:
            activity.intensity_factor = round(activity.normalized_power_w / ftp, 2)

    db.add(activity)
    db.commit()
    db.refresh(activity)

    # Update training load
    try:
        update_training_load(db, ftp)
    except Exception as e:
        logger.warning(f"Training load update failed: {e}")

    return {"activity": activity.to_dict(), "message": "Activity imported successfully"}


@router.delete("/{activity_id}")
def delete_activity(activity_id: int, db: Session = Depends(get_db),         _session = Depends(require_session)):
    """Delete an activity."""
    activity = db.query(Activity).filter(Activity.id == activity_id).first()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")

    # Delete source file
    if activity.source_file and os.path.exists(activity.source_file):
        try:
            os.remove(activity.source_file)
        except OSError:
            pass

    db.delete(activity)
    db.commit()
    return {"message": "Activity deleted"}


@router.post("/upload-multiple")
async def upload_multiple(files: list[UploadFile] = File(...), db: Session = Depends(get_db),         _session = Depends(require_session)):
    """Upload multiple activity files at once."""
    results = []
    for file in files:
        try:
            # Save
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            safe_name = f"{timestamp}_{file.filename}"
            filepath = DATA_DIR / safe_name
            with open(filepath, "wb") as f:
                content = await file.read()
                f.write(content)

            # Parse
            result = parse_activity_file(str(filepath))

            start_time = result["start_time"]
            if isinstance(start_time, str):
                start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))

            activity = Activity(
                name=result.get("name", file.filename),
                sport=result.get("sport", "cycling"),
                start_time=start_time,
                distance_m=result.get("distance_m", 0),
                moving_time_s=result.get("moving_time_s", 0),
                elapsed_time_s=result.get("elapsed_time_s", 0),
                avg_speed_ms=result.get("avg_speed_ms", 0),
                max_speed_ms=result.get("max_speed_ms", 0),
                elevation_gain_m=result.get("elevation_gain_m", 0),
                avg_heartrate=result.get("avg_heartrate"),
                max_heartrate=result.get("max_heartrate"),
                avg_power_w=result.get("avg_power_w"),
                max_power_w=result.get("max_power_w"),
                normalized_power_w=result.get("normalized_power_w"),
                avg_cadence=result.get("avg_cadence"),
                calories_kcal=result.get("calories_kcal"),
                kilojoules_kj=result.get("kilojoules_kj"),
                track_geojson=result.get("track_geojson"),
                streams=result.get("streams"),
                source_file=str(filepath),
                file_format=result.get("file_format", "fit"),
            )
            db.add(activity)
            db.commit()
            results.append({"filename": file.filename, "status": "ok", "activity_id": activity.id})
        except Exception as e:
            results.append({"filename": file.filename, "status": "error", "error": str(e)})
            logger.exception(f"Failed to upload {file.filename}")

    # Recompute training load
    try:
        update_training_load(db)
    except Exception:
        pass

    return {"results": results}
