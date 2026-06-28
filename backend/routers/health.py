from routers.auth import require_session
"""Health data endpoints."""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from services.health_metrics import (
    create_checkin, get_checkins, compute_dashboard_summary,
    compute_hrv_trend, compute_resting_hr_trend, compute_sleep_trend,
    compute_recovery_trend, auto_compute_vo2max,
)

router = APIRouter(prefix="/api/health", tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/")
def health_home():
    return {"status": "ok", "message": "Health & Wellness API"}


@router.get("/dashboard")
def health_dashboard(db: Session = Depends(get_db),         _session = Depends(require_session)):
    """Get health dashboard summary."""
    summary = compute_dashboard_summary(db)

    # Auto-compute VO2max
    vo2max = auto_compute_vo2max(db)
    if vo2max:
        summary["estimated_vo2max"] = vo2max

    return summary


@router.get("/checkins")
def list_checkins(days: int = 90, db: Session = Depends(get_db),         _session = Depends(require_session)):
    """Get health check-in history."""
    return get_checkins(db, days)


@router.post("/checkins")
def create_or_update_checkin(data: dict, db: Session = Depends(get_db),         _session = Depends(require_session)):
    """Create or update a daily health check-in."""
    checkin = create_checkin(db, data)
    if not checkin:
        raise HTTPException(status_code=400, detail="Could not create checkin. Date is required.")
    return checkin.to_dict()


@router.get("/hrv")
def hrv_trend(days: int = 30, db: Session = Depends(get_db),         _session = Depends(require_session)):
    """Get HRV trend data."""
    return compute_hrv_trend(db, days)


@router.get("/resting-hr")
def resting_hr_trend(days: int = 90, db: Session = Depends(get_db),         _session = Depends(require_session)):
    """Get resting heart rate trend."""
    return compute_resting_hr_trend(db, days)


@router.get("/sleep")
def sleep_trend(days: int = 90, db: Session = Depends(get_db),         _session = Depends(require_session)):
    """Get sleep trend data."""
    return compute_sleep_trend(db, days)


@router.get("/recovery")
def recovery_trend(days: int = 30, db: Session = Depends(get_db),         _session = Depends(require_session)):
    """Get recovery and body battery trends."""
    return compute_recovery_trend(db, days)


@router.get("/vo2max")
def vo2max_estimate(db: Session = Depends(get_db),         _session = Depends(require_session)):
    """Estimate VO2max from recent performance."""
    vo2max = auto_compute_vo2max(db)
    return {"estimated_vo2max": vo2max}
