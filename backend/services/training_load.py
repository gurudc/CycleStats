"""Training Load calculations (TrainingPeaks-style Performance Management Chart).

Metrics:
  - **TSS**: Training Stress Score per activity
  - **CTL**: Chronic Training Load (42-day weighted avg) — *fitness*
  - **ATL**: Acute Training Load (7-day weighted avg) — *fatigue*
  - **TSB**: Training Stress Balance (CTL - ATL) — *form*
  - **Daily load**: aggregated daily TSS

Formulas (Coggan):
  CTL[n] = TSS_day[n] × (1 - e^(-1/42)) + CTL[n-1] × e^(-1/42)
  ATL[n] = TSS_day[n] × (1 - e^(-1/7)) + ATL[n-1] × e^(-1/7)
  TSB[n] = CTL[n] - ATL[n]
"""
import math
import logging
from datetime import datetime, timedelta, date
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import Activity, DailyTrainingLoad

logger = logging.getLogger(__name__)

# Time constants (days)
CTL_TC = 42.0   # Fitness time constant
ATL_TC = 7.0    # Fatigue time constant


def compute_daily_tss_summary(db: Session, days_back=365):
    """Compute daily TSS totals from all activities in the date range."""
    cutoff = datetime.utcnow() - timedelta(days=days_back)
    activities = db.query(Activity).filter(
        Activity.start_time >= cutoff,
        Activity.tss.isnot(None)
    ).order_by(Activity.start_time).all()

    daily_tss = defaultdict(float)
    daily_kj = defaultdict(float)
    daily_distance = defaultdict(float)
    daily_time = defaultdict(float)

    for act in activities:
        day = act.start_time.date()
        daily_tss[day] += act.tss if act.tss else 0
        daily_kj[day] += act.kilojoules_kj if act.kilojoules_kj else 0
        daily_distance[day] += act.distance_m / 1000 if act.distance_m else 0
        daily_time[day] += act.moving_time_s if act.moving_time_s else 0

    return daily_tss, daily_kj, daily_distance, daily_time


def compute_ctl_atl_tsb(daily_tss, ctl_init=0, atl_init=0, window_days=90):
    """Compute CTL, ATL, TSB from daily TSS data using a rolling window.

    Args:
        daily_tss: dict of {date: daily_tss_score}
        ctl_init: starting CTL value (default 0)
        atl_init: starting ATL value (default 0)
        window_days: only use the last N days (default 90)

    Returns:
        list of dicts with date, daily_tss, ctl, atl, tsb
    """
    from datetime import timedelta
    sorted_days = sorted(daily_tss.keys())
    if not sorted_days:
        return []

    # Apply rolling window: fill all calendar days in the window with 0 TSS
    if window_days and sorted_days:
        from datetime import timedelta
        window_start = sorted_days[-1] - timedelta(days=window_days)
        # Fill in missing days with 0 TSS
        full_range = []
        current = window_start
        while current <= sorted_days[-1]:
            full_range.append(current)
            current += timedelta(days=1)
        sorted_days = full_range
        for d in full_range:
            if d not in daily_tss:
                daily_tss[d] = 0

    ctl = ctl_init
    atl = atl_init
    results = []

    for day in sorted_days:
        tss = daily_tss[day]

        # Exponential weighted moving average
        ctl = ctl * math.exp(-1 / CTL_TC) + tss * (1 - math.exp(-1 / CTL_TC))
        atl = atl * math.exp(-1 / ATL_TC) + tss * (1 - math.exp(-1 / ATL_TC))
        tsb = ctl - atl

        results.append({
            "date": day.isoformat() if hasattr(day, 'isoformat') else str(day),
            "daily_tss": round(tss, 1),
            "ctl": round(ctl, 1),
            "atl": round(atl, 1),
            "tsb": round(tsb, 1),
        })

    return results


def compute_activity_tss(activity: Activity, ftp: float = None):
    """Compute TSS for a single activity if not already computed.

    TSS = (s × NP × IF) / (FTP × 3600) × 100
    where IF = NP / FTP

    Simplified for when NP isn't available:
    TSS ≈ (s × avg_power × (avg_power/FTP)) / (FTP × 3600) × 100
        = (s × avg_power²) / (FTP² × 3600) × 100
    """
    if activity.tss is not None:
        return activity.tss

    if not ftp:
        return None

    np = activity.normalized_power_w or activity.avg_power_w
    if not np or np <= 0:
        return None

    if_val = np / ftp
    duration_s = activity.moving_time_s or activity.elapsed_time_s or 3600

    tss = (duration_s * np * if_val) / (ftp * 3600) * 100
    return round(tss, 1)


def update_training_load(db: Session, ftp=None):
    """Compute and store daily training load for all activities with TSS."""
    if ftp is None:
        # Try to estimate FTP from the best activities
        from services.power_duration import compute_mmp_curve, estimate_ftp
        all_ids = [a.id for a in db.query(Activity.id).all()]
        if not all_ids:
            return
        mmp = compute_mmp_curve(all_ids, db)
        ftp = estimate_ftp(mmp)

    # Compute TSS for activities that don't have it
    for activity in db.query(Activity).filter(Activity.tss.is_(None)).all():
        if activity.streams and "power" in activity.streams and ftp:
            powers = [p for p in activity.streams["power"] if p is not None]
            if powers:
                from services.power_duration import compute_tss
                np = activity.normalized_power_w
                if not np:
                    from services.power_duration import _normalized_power
                    np = _normalized_power(powers)
                tss = compute_tss(powers, np, ftp, len(powers) / 3600)
                if tss:
                    activity.tss = tss
                    activity.normalized_power_w = np
                    if np:
                        activity.intensity_factor = round(np / ftp, 2)
                    db.commit()

    # Aggregate daily
    daily_tss, daily_kj, daily_distance, daily_time = compute_daily_tss_summary(db)
    pmc = compute_ctl_atl_tsb(daily_tss)

    # Store in database
    for entry in pmc:
        try:
            d = datetime.strptime(entry["date"], "%Y-%m-%d").date()
        except ValueError:
            continue

        existing = db.query(DailyTrainingLoad).filter(
            func.date(DailyTrainingLoad.date) == d
        ).first()

        if existing:
            existing.daily_tss = entry["daily_tss"]
            existing.ctl = entry["ctl"]
            existing.atl = entry["atl"]
            existing.tsb = entry["tsb"]
            existing.daily_kj = daily_kj.get(d, 0)
            existing.daily_distance_km = daily_distance.get(d, 0)
            existing.daily_time_s = daily_time.get(d, 0)
        else:
            row = DailyTrainingLoad(
                date=datetime.combine(d, datetime.min.time()),
                daily_tss=entry["daily_tss"],
                ctl=entry["ctl"],
                atl=entry["atl"],
                tsb=entry["tsb"],
                daily_kj=daily_kj.get(d, 0),
                daily_distance_km=daily_distance.get(d, 0),
                daily_time_s=daily_time.get(d, 0),
            )
            db.add(row)

    db.commit()

    return {"pmc": pmc, "ftp": ftp}


def get_pmc(db: Session, days=90):
    """Get Performance Management Chart data."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = db.query(DailyTrainingLoad).filter(
        DailyTrainingLoad.date >= cutoff
    ).order_by(DailyTrainingLoad.date).all()
    return [r.to_dict() for r in rows]
