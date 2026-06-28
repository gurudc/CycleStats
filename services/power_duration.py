"""Power-duration curve modeling (Xert-style).

Models:
  - Best Mean Maximal Power (MMP) curve - best average power for any duration
  - FTP estimation - from MMP curve (best 20-min power x 0.95, or CP)
  - Anaerobic Work Capacity (AWC) - Xert W' above CP
  - Power Profile - 5s, 1m, 5m, 20m, FTP, etc.
  - Xert Stress Score (XSS) equivalent - work above threshold
  - IF (Intensity Factor) relative to FTP

Optimizations:
  - File-based cache for power-curve / power-profile / FTP results
  - Cache invalidated via activity count+max-id signature
  - Shared power extraction avoids duplicate work across endpoints
"""
import math
import requests
import json
import os
from datetime import datetime
from collections import defaultdict
from sqlalchemy.orm import Session

from database import Activity, PowerProfile

# -- File-based caches --
STRAVA_CACHE_FILE = "/tmp/strava_streams_cache.json"
MMP_CACHE_FILE = "/tmp/cyclestats_mmp_cache.json"

DURATIONS = [
    1, 5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 300,
    420, 600, 900, 1200, 1800, 2700, 3600, 5400, 7200, 10800, 14400,
]
CURVE_DURATIONS = [1, 5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 300,
                   420, 600, 900, 1200, 1800, 2700, 3600]
PROFILE_DURATIONS = {5: "5s", 60: "1m", 300: "5m", 1200: "20m", 3600: "60m"}

_strava_cache = None


def load_strava_cache():
    if os.path.exists(STRAVA_CACHE_FILE):
        try:
            with open(STRAVA_CACHE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_strava_cache(cache):
    try:
        with open(STRAVA_CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except Exception:
        pass


def get_strava_token():
    try:
        with open("/opt/cyclestats/backend/data/strava_state.json") as f:
            config = json.load(f)
        return config.get("access_token")
    except Exception:
        return None


def fetch_strava_streams(activity_id):
    global _strava_cache
    if _strava_cache is None:
        _strava_cache = load_strava_cache()
    key = str(activity_id)
    if key in _strava_cache:
        return _strava_cache[key]
    token = get_strava_token()
    if not token:
        return None
    try:
        resp = requests.get(
            f"https://www.strava.com/api/v3/activities/{activity_id}/streams",
            headers={"Authorization": f"Bearer {token}"},
            params={"keys": "time,watts,heartrate,cadence,altitude,distance",
                    "key_by_type": "true"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        streams = {}
        for src_key, dest_key in [
            ("time", "time"), ("watts", "power"), ("heartrate", "heartrate"),
            ("cadence", "cadence"), ("altitude", "altitude"), ("distance", "distance"),
        ]:
            if src_key in data:
                streams[dest_key] = data[src_key]["data"]
        if streams:
            _strava_cache[key] = streams
            save_strava_cache(_strava_cache)
        return streams if streams else None
    except Exception:
        return None


# -- MMP Cache ----------------------------------------------------


def _activity_sig(db: Session) -> str:
    count = db.query(Activity).count()
    latest = db.query(Activity.id).order_by(Activity.id.desc()).first()
    latest_id = latest[0] if latest else 0
    return f"v2_{count}_{latest_id}"


def _load_cache(sig: str):
    if not os.path.exists(MMP_CACHE_FILE):
        return (None,) * 5
    try:
        with open(MMP_CACHE_FILE) as f:
            data = json.load(f)
        if data.get("sig") == sig:
            return (
                data.get("mmp"),
                data.get("profile"),
                data.get("ftp"),
                data.get("awc"),
                data.get("wp"),
            )
    except Exception:
        pass
    return (None,) * 5


def _save_cache(sig, mmp=None, profile=None, ftp=None, awc=None, wp=None):
    try:
        with open(MMP_CACHE_FILE, "w") as f:
            json.dump({
                "sig": sig, "mmp": mmp, "profile": profile,
                "ftp": ftp, "awc": awc, "wp": wp,
            }, f)
    except Exception:
        pass


def _extract_power_data(activities):
    result = []
    for act in activities:
        # Streams stored in Strava format (watts) or translated format (power)
        power_key = "watts" if (act.streams and "watts" in act.streams) else "power"
        if act.streams and power_key in act.streams:
            raw = act.streams[power_key]
            # Strava format: {"data": [...], "series_type": ...} vs simple list
            if isinstance(raw, dict) and "data" in raw:
                p = [x for x in raw["data"] if x is not None]
            else:
                p = [x for x in raw if x is not None]
            if len(p) > 10:
                result.append((act.id, p))
    return result


def _compute_mmp(all_powers, durations=None):
    if durations is None:
        durations = DURATIONS
    mmp = {}
    for d in durations:
        best = 0
        for _, powers in all_powers:
            if len(powers) >= d:
                avg = _best_avg_for_duration(powers, d)
                if avg and avg > best:
                    best = avg
        if best > 0:
            mmp[d] = round(best, 1)
    return mmp


def _build_mmp_cache(db: Session):
    """Build MMP + profile + FTP + AWC in one pass and cache."""
    activities = (
        db.query(Activity)
        .filter(Activity.id > 0)
        .order_by(Activity.start_time.desc())
        .limit(200)
        .all()
    )
    all_powers = _extract_power_data(activities)

    if not all_powers:
        sig = _activity_sig(db)
        _save_cache(sig, mmp={}, profile={}, ftp=None, awc=None, wp=None)
        return {}, {}, None, None, None

    mmp_full = _compute_mmp(all_powers, DURATIONS)
    mmp_curve = {k: v for k, v in mmp_full.items() if k in CURVE_DURATIONS}

    profile = {}
    for dur_sec, label in PROFILE_DURATIONS.items():
        best = 0
        for _, powers in all_powers:
            if len(powers) >= dur_sec:
                avg = _best_avg_for_duration(powers, dur_sec)
                if avg and avg > best:
                    best = avg
        if best:
            profile[label] = round(best, 1)

    ftp = estimate_ftp(mmp_full)
    awc, wp = estimate_awc(mmp_full, ftp)
    if ftp:
        profile["FTP"] = ftp

    sig = _activity_sig(db)
    _save_cache(sig, mmp=mmp_curve, profile=profile, ftp=ftp, awc=awc, wp=wp)
    return mmp_curve, profile, ftp, awc, wp


# -- Public helpers used by routers ------------------------------


def compute_mmp_curve(activity_ids, db: Session):
    activities = db.query(Activity).filter(Activity.id.in_(activity_ids)).all()
    all_powers = _extract_power_data(activities)
    return _compute_mmp(all_powers, DURATIONS)


def compute_activity_power_duration(powers, times):
    clean = [p for p in powers if p is not None]
    if len(clean) < 5:
        return {}
    curve = {}
    for d in CURVE_DURATIONS:
        if len(clean) < d:
            continue
        best = _best_avg_for_duration(clean, d)
        if best:
            curve[d] = round(best, 1)
    return curve


def _best_avg_for_duration(powers, duration_s):
    if len(powers) < duration_s:
        return None
    best = window_sum = sum(powers[:duration_s])
    for i in range(duration_s, len(powers)):
        window_sum = window_sum - powers[i - duration_s] + powers[i]
        if window_sum > best:
            best = window_sum
    return best / duration_s


def estimate_ftp(mmp_curve):
    if not mmp_curve:
        return None
    if 1200 in mmp_curve:
        return round(mmp_curve[1200] * 0.95, 1)
    for target in [3600, 2700, 1800]:
        if target in mmp_curve:
            return round(mmp_curve[target], 1)
    long_durs = sorted(d for d in mmp_curve if d >= 600)
    if long_durs:
        nearest = min(long_durs, key=lambda x: abs(x - 1200))
        factor = 0.95 if nearest <= 1800 else 1.0
        return round(mmp_curve[nearest] * factor, 1)
    return round(mmp_curve[max(mmp_curve)], 1)


def estimate_awc(mmp_curve, ftp):
    if not mmp_curve or not ftp:
        return None, None
    p60 = mmp_curve.get(60)
    p5 = mmp_curve.get(5)
    if p60 and p60 > ftp:
        w_prime = (p60 - ftp) * 60 / 1000
    elif p5 and p5 > ftp:
        w_prime = (p5 - ftp) * 5 / 1000
    else:
        p300 = mmp_curve.get(300)
        if p300 and p300 > ftp:
            w_prime = (p300 - ftp) * 300 / 1000 * 0.2
        else:
            w_prime = None
    if w_prime is not None:
        awc = round(w_prime, 1)
        return awc, awc
    return None, None


# -- Cached endpoint functions (used by routers/training.py) ------


def compute_power_curve(db: Session):
    sig = _activity_sig(db)
    mmp, *_ = _load_cache(sig)
    if mmp is not None:
        return mmp
    mmp, *_ = _build_mmp_cache(db)
    return mmp or {}


def compute_power_profile(db: Session, ftp=None):
    sig = _activity_sig(db)
    _, profile, cached_ftp, *_ = _load_cache(sig)
    if profile is not None:
        if ftp is not None and cached_ftp != ftp:
            profile["FTP"] = ftp
        return profile
    _, profile, *_ = _build_mmp_cache(db)
    if ftp is not None:
        profile["FTP"] = ftp
    return profile or {}


def compute_ftp_cached(db: Session):
    sig = _activity_sig(db)
    _, _, ftp, awc, wp = _load_cache(sig)
    if ftp is not None:
        return {"ftp": ftp, "awc_kj": awc, "w_prime_kj": wp, "source": "cached"}
    _, _, ftp, awc, wp = _build_mmp_cache(db)
    return {"ftp": ftp, "awc_kj": awc, "w_prime_kj": wp, "source": "computed"}


def compute_xss(powers, ftp, sampling_interval=1.0):
    if not powers or not ftp:
        return None
    clean = [p for p in powers if p is not None and p > 0]
    if not clean:
        return None
    xss = 0
    threshold = ftp
    interval_hr = sampling_interval / 3600
    for p in clean:
        ratio = p / threshold
        if ratio < 0.75:
            xss += ratio * 0.2
        elif ratio < 1.0:
            xss += ratio * 0.5
        elif ratio < 1.2:
            xss += ratio * 1.0
        else:
            xss += ratio * 2.0
    xss = xss * interval_hr * 100
    return round(xss, 1)


def compute_tss(powers, np, ftp, duration_hours):
    if not powers or not ftp or not np:
        return None
    if_val = np / ftp
    duration_s = len(powers)
    tss = (duration_s * np * if_val) / (ftp * 3600) * 100
    return round(tss, 1)
