"""Health metrics analysis and trends.

Processes daily health check-in data to compute:
  - Resting HR trends (7-day, 30-day)
  - HRV trends (RMSSD, SDNN)
  - Sleep trends (duration, quality)
  - Recovery scores
  - Body Battery trends
  - VO2max progression
  - Weight trends
  - Correlations between metrics
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import HealthCheckin, Activity

logger = logging.getLogger(__name__)


def create_checkin(db: Session, data: dict):
    """Create or update a daily health check-in."""
    date_str = data.get("date")
    if not date_str:
        return None

    try:
        check_date = datetime.strptime(date_str[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        check_date = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    existing = db.query(HealthCheckin).filter(
        func.date(HealthCheckin.date) == check_date.date()
    ).first()

    if existing:
        for key, value in data.items():
            if hasattr(existing, key) and value is not None:
                setattr(existing, key, value)
        checkin = existing
    else:
        checkin = HealthCheckin(date=check_date, **{k: v for k, v in data.items() if k != "date"})
        db.add(checkin)

    db.commit()
    db.refresh(checkin)
    return checkin


def get_checkins(db: Session, days=90):
    """Get health check-ins for the last N days."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    results = db.query(HealthCheckin).filter(
        HealthCheckin.date >= cutoff
    ).order_by(HealthCheckin.date).all()
    return [r.to_dict() for r in results]


def compute_hrv_trend(db: Session, days=30):
    """Compute HRV trend over time."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    results = db.query(HealthCheckin).filter(
        HealthCheckin.date >= cutoff,
        HealthCheckin.hrv_rmssd.isnot(None)
    ).order_by(HealthCheckin.date).all()
    return [{"date": r.date.isoformat()[:10], "rmssd": r.hrv_rmssd, "sdnn": r.hrv_sdnn} for r in results]


def compute_resting_hr_trend(db: Session, days=90):
    """Compute resting HR trend with 7-day rolling average."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    results = db.query(HealthCheckin).filter(
        HealthCheckin.date >= cutoff,
        HealthCheckin.resting_hr.isnot(None)
    ).order_by(HealthCheckin.date).all()

    data = [{"date": r.date.isoformat()[:10], "resting_hr": r.resting_hr} for r in results]

    # 7-day rolling avg
    if len(data) >= 7:
        for i in range(6, len(data)):
            window = [d["resting_hr"] for d in data[i - 6:i + 1] if d["resting_hr"]]
            data[i]["resting_hr_7d_avg"] = round(sum(window) / len(window), 1) if window else None

    return data


def compute_sleep_trend(db: Session, days=90):
    """Compute sleep trends."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    results = db.query(HealthCheckin).filter(
        HealthCheckin.date >= cutoff,
        HealthCheckin.sleep_hours.isnot(None)
    ).order_by(HealthCheckin.date).all()
    return [{
        "date": r.date.isoformat()[:10],
        "sleep_hours": r.sleep_hours,
        "sleep_score": r.sleep_score,
        "deep_sleep": r.deep_sleep_hours,
        "rem_sleep": r.rem_sleep_hours,
        "light_sleep": r.light_sleep_hours,
    } for r in results]


def compute_recovery_trend(db: Session, days=30):
    """Compute recovery score and body battery trends."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    results = db.query(HealthCheckin).filter(
        HealthCheckin.date >= cutoff
    ).order_by(HealthCheckin.date).all()
    return [{
        "date": r.date.isoformat()[:10],
        "recovery_score": r.recovery_score,
        "body_battery_high": r.body_battery_high,
        "body_battery_low": r.body_battery_low,
        "stress_level": r.stress_level,
    } for r in results]


def compute_dashboard_summary(db: Session):
    """Compute summary stats for the health dashboard."""
    latest_checkin = db.query(HealthCheckin).order_by(HealthCheckin.date.desc()).first()

    # 7-day averages
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    week_data = db.query(HealthCheckin).filter(HealthCheckin.date >= seven_days_ago).all()

    summary = {
        "latest": latest_checkin.to_dict() if latest_checkin else None,
        "avg_resting_hr_7d": None,
        "avg_hrv_rmssd_7d": None,
        "avg_sleep_7d": None,
        "avg_recovery_7d": None,
        "total_steps_7d": 0,
    }

    if week_data:
        hrs = [c.resting_hr for c in week_data if c.resting_hr]
        if hrs:
            summary["avg_resting_hr_7d"] = round(sum(hrs) / len(hrs), 1)
        hrvs = [c.hrv_rmssd for c in week_data if c.hrv_rmssd]
        if hrvs:
            summary["avg_hrv_rmssd_7d"] = round(sum(hrvs) / len(hrvs), 1)
        sleeps = [c.sleep_hours for c in week_data if c.sleep_hours]
        if sleeps:
            summary["avg_sleep_7d"] = round(sum(sleeps) / len(sleeps), 1)
        recs = [c.recovery_score for c in week_data if c.recovery_score]
        if recs:
            summary["avg_recovery_7d"] = round(sum(recs) / len(recs), 1)
        summary["total_steps_7d"] = sum(c.steps for c in week_data if c.steps)

    return summary


def auto_compute_vo2max(db: Session):
    """Estimate VO2max from recent best performances."""
    # Simple estimation from best 20-min power (cycling) or best running performance
    # Cycling: VO2max ≈ (10.8 × watts) / body_weight_in_kg + 7
    activities = db.query(Activity).filter(
        Activity.avg_power_w.isnot(None),
        Activity.moving_time_s >= 1200  # At least 20 min
    ).order_by(Activity.avg_power_w.desc()).limit(3).all()

    if not activities:
        return None

    weight = None
    latest = db.query(HealthCheckin).filter(
        HealthCheckin.weight_kg.isnot(None)
    ).order_by(HealthCheckin.date.desc()).first()
    if latest:
        weight = latest.weight_kg

    if not weight:
        return None

    best_20min_power = max(a.avg_power_w for a in activities)
    # VO2max (ml/kg/min) ≈ 10.8 × (P / weight) + 7
    vo2max = 10.8 * (best_20min_power / weight) + 7
    return round(vo2max, 1)
