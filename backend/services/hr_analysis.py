"""Compute cardiac drift and HR metrics - exclude stopped time."""
import json

def _arr(streams, key):
    v = streams.get(key, {})
    if isinstance(v, dict) and "data" in v:
        return v["data"]
    if isinstance(v, list):
        return v
    return []

def _moving_only(streams, keys):
    """Return aligned arrays filtered to moving=True only."""
    arrs = {k: _arr(streams, k) for k in keys}
    n = min(len(v) for v in arrs.values()) if arrs else 0
    if n == 0:
        return {k: [] for k in keys}
    moving = _arr(streams, "moving")
    if len(moving) < n:
        moving = [True] * n
    result = {k: [] for k in keys}
    for i in range(n):
        if moving[i]:
            for k in keys:
                v = arrs[k]
                result[k].append(v[i] if i < len(v) else 0)
    return result

def compute_hr_metrics(streams):
    f = _moving_only(streams, ["time", "heartrate", "watts", "cadence"])
    hr = f["heartrate"]
    power = f["watts"]
    cad = f["cadence"]

    if not hr or len(hr) < 30:
        return {}

    valid_hr = [h for h in hr if h and h > 0]
    if len(valid_hr) < 30:
        return {}
    max_hr = max(valid_hr)
    avg_hr = sum(valid_hr) / len(valid_hr)
    emax = max(max_hr, 185)

    zones = [(1, 0, 0.60, "Recovery"), (2, 0.60, 0.70, "Endurance"),
             (3, 0.70, 0.80, "Tempo"), (4, 0.80, 0.90, "Threshold"),
             (5, 0.90, 1.50, "VO2Max")]
    zs = {z[0]: 0 for z in zones}
    total = 0
    for h in hr:
        if h and h > 0:
            pct = h / emax
            for zn, zlo, zhi, _ in zones:
                if zlo <= pct < zhi:
                    zs[zn] += 1
                    break
            total += 1
    hr_zp = {}
    for zn, _, _, znm in zones:
        if total > 0:
            hr_zp[znm] = round(zs[zn] / total * 100, 1)

    n = len(hr)
    def sa(arr, s, e):
        vv = [v for v in arr[s:e] if v and v > 0]
        return sum(vv)/len(vv) if vv else 0

    f1 = n // 3
    l1 = 2 * n // 3
    hf = sa(hr, 0, f1)
    hl = sa(hr, l1, n)
    drift = round((hl - hf) / hf * 100, 1) if hf > 0 else None

    pf = sa(power, 0, f1)
    pl = sa(power, l1, n)
    if hf > 0 and hl > 0 and pf > 0 and pl > 0:
        dec = round((pl/hl - pf/hf) / (pf/hf) * 100, 1)
    else:
        dec = None

    vp = [p for p in power if p and p > 0]
    ap = sum(vp)/len(vp) if vp else 0
    ef = round(ap / avg_hr, 2) if avg_hr > 0 else None

    rec = None
    if len(hr) > 120:
        lm = [h for h in hr[-60:] if h and h > 0]
        pm = [h for h in hr[-120:-60] if h and h > 0]
        if lm and pm:
            rec = round(sum(pm)/len(pm) - sum(lm)/len(lm), 1)

    vc = [c for c in cad if c and c > 0]
    ac = round(sum(vc)/len(vc)) if vc else None

    return {
        "max_hr": round(max_hr), "avg_hr": round(avg_hr, 0),
        "est_max_hr": round(emax),
        "cardiac_drift_pct": drift,
        "efficiency_factor": ef,
        "decoupling_pct": dec,
        "hr_recovery_bpm": rec,
        "hr_zone_pcts": hr_zp,
        "avg_cadence": ac, "data_quality": len(hr),
    }
