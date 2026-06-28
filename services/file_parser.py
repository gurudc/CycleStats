"""Parse FIT, GPX, and TCX activity files into standardized dicts."""
import os
import json
import logging
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)


def parse_activity_file(filepath):
    """Parse any supported activity file. Returns a dict of Activity data."""
    import gzip, tempfile
    ext = os.path.splitext(filepath)[1].lower()
    
    # Handle .gz compressed files
    if ext == ".gz" or filepath.endswith(".fit.gz") or filepath.endswith(".gpx.gz") or filepath.endswith(".tcx.gz"):
        try:
            with gzip.open(filepath, "rb") as f:
                raw = f.read()
            # Determine inner format from filename
            base = os.path.basename(filepath)
            if ".gpx" in base:
                inner_ext = ".gpx"
            elif ".tcx" in base:
                inner_ext = ".tcx"
            else:
                inner_ext = ".fit"
            # Write to temp file and parse
            with tempfile.NamedTemporaryFile(suffix=inner_ext, delete=False) as tmp:
                tmp.write(raw)
                tmp_path = tmp.name
            try:
                if inner_ext == ".fit":
                    result = _parse_fit(tmp_path)
                elif inner_ext == ".gpx":
                    result = _parse_gpx(tmp_path)
                elif inner_ext == ".tcx":
                    result = _parse_tcx(tmp_path)
                return result
            finally:
                os.unlink(tmp_path)
        except Exception as e:
            raise ValueError(f"Failed to parse compressed file {filepath}: {e}")
    
    if ext == ".fit":
        return _parse_fit(filepath)
    elif ext == ".gpx":
        return _parse_gpx(filepath)
    elif ext == ".tcx":
        return _parse_tcx(filepath)
    else:
        raise ValueError(f"Unsupported file format: {ext}")


def _parse_fit(filepath):
    """Parse a FIT file using fitparse library."""
    from fitparse import FitFile

    fitfile = FitFile(filepath)
    fitfile.parse()

    records = []
    laps = []
    session_data = {}

    for msg in fitfile.messages:
        if msg.name == "record":
            record = {field.name: field.value for field in msg.fields}
            records.append(record)
        elif msg.name == "lap":
            lap = {field.name: field.value for field in msg.fields}
            laps.append(lap)
        elif msg.name == "session":
            session_data = {field.name: field.value for field in msg.fields}

    if not records:
        logger.warning(f"No record messages found in FIT file: {filepath}")
        return _empty_result(filepath, "fit")

    # Extract streams
    streams = _extract_streams(records)
    result = _compute_metrics_from_streams(streams, filepath, "fit")

    # Override with session-level data if available (more accurate)
    if session_data:
        _apply_session_data(result, session_data)

    # Process laps
    if laps:
        result["laps"] = [_process_lap(l) for l in laps]

    # Build simplified GeoJSON track
    result["track_geojson"] = _build_geojson(streams)

    result["streams"] = streams
    result["source_file"] = filepath

    return result


def _parse_gpx(filepath):
    """Parse a GPX file using gpxpy."""
    import gpxpy

    with open(filepath, "r", encoding="utf-8") as f:
        gpx = gpxpy.parse(f)

    if not gpx.tracks:
        logger.warning(f"No tracks found in GPX file: {filepath}")
        return _empty_result(filepath, "gpx")

    track = gpx.tracks[0]
    points = []
    for segment in track.segments:
        for pt in segment.points:
            points.append({
                "timestamp": pt.time,
                "position_lat": pt.latitude,
                "position_long": pt.longitude,
                "altitude": pt.elevation,
                "enhanced_altitude": pt.elevation,
            })

    if not points:
        return _empty_result(filepath, "gpx")

    # GPX may not have HR/power. Try extensions.
    for i, pt in enumerate(points):
        for ext in (track.segments[0].points[i].extensions if i < len(track.segments[0].points) else []):
            # Some GPX files embed HR and power in extensions
            pass  # Hard to standardize — best-effort below

    # Convert to our record format
    records = []
    for pt in points:
        r = {
            "timestamp": pt["timestamp"],
            "position_lat": pt["position_lat"],
            "position_long": pt["position_long"],
            "altitude": pt["altitude"],
            "enhanced_altitude": pt["enhanced_altitude"],
        }
        records.append(r)

    streams = _extract_streams(records)
    result = _compute_metrics_from_streams(streams, filepath, "gpx")

    # Get name from track
    if track.name:
        result["name"] = track.name

    result["track_geojson"] = _build_geojson(streams)
    result["streams"] = streams
    result["source_file"] = filepath

    return result


def _parse_tcx(filepath):
    """Parse a TCX file using XML parsing."""
    import xml.etree.ElementTree as ET

    ns = {
        "ns": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2",
        "ext": "http://www.garmin.com/xmlschemas/ActivityExtension/v2",
    }

    tree = ET.parse(filepath)
    root = tree.getroot()

    activities = root.findall(".//ns:Activity", ns)
    if not activities:
        return _empty_result(filepath, "tcx")

    activity = activities[0]
    sport = activity.get("Sport", "")

    laps_xml = activity.findall("ns:Lap", ns)
    records = []
    laps = []

    for lap_elem in laps_xml:
        lap_start = lap_elem.find("ns:StartTime", ns)
        lap_start_time = datetime.fromisoformat(lap_start.text.replace("Z", "+00:00")) if lap_start is not None else None

        lap_data = {"start_time": lap_start_time, "distance_m": 0, "time_s": 0}

        for track in lap_elem.findall("ns:Track", ns):
            for pt in track.findall("ns:Trackpoint", ns):
                record = {}
                time_elem = pt.find("ns:Time", ns)
                if time_elem is not None:
                    record["timestamp"] = datetime.fromisoformat(time_elem.text.replace("Z", "+00:00"))

                pos = pt.find("ns:Position", ns)
                if pos is not None:
                    lat = pos.find("ns:LatitudeDegrees", ns)
                    lon = pos.find("ns:LongitudeDegrees", ns)
                    if lat is not None:
                        record["position_lat"] = float(lat.text)
                    if lon is not None:
                        record["position_long"] = float(lon.text)

                alt = pt.find("ns:AltitudeMeters", ns)
                if alt is not None:
                    record["altitude"] = float(alt.text)

                hr = pt.find("ns:HeartRateBpm/ns:Value", ns)
                if hr is not None:
                    record["heart_rate"] = float(hr.text)

                cad = pt.find("ns:Cadence", ns)
                if cad is not None:
                    record["cadence"] = float(cad.text)

                # Extensions
                ext = pt.find("ns:Extensions", ns)
                if ext is not None:
                    tpx = ext.find("ext:TPX", ns)
                    if tpx is not None:
                        power = tpx.find("ext:Watts", ns)
                        if power is not None:
                            record["power"] = float(power.text)
                        speed = tpx.find("ext:Speed", ns)
                        if speed is not None:
                            record["speed"] = float(speed.text)

                records.append(record)

        # Lap totals
        dist_elem = lap_elem.find("ns:DistanceMeters", ns)
        if dist_elem is not None:
            lap_data["distance_m"] = float(dist_elem.text)
        time_elem = lap_elem.find("ns:TotalTimeSeconds", ns)
        if time_elem is not None:
            lap_data["time_s"] = float(time_elem.text)

        laps.append(lap_data)

    if not records:
        return _empty_result(filepath, "tcx")

    streams = _extract_streams(records)
    result = _compute_metrics_from_streams(streams, filepath, "tcx")
    result["sport"] = sport.lower() if sport else "cycling"

    if laps:
        result["laps"] = laps

    result["track_geojson"] = _build_geojson(streams)
    result["streams"] = streams
    result["source_file"] = filepath

    return result


def _extract_streams(records):
    """Extract time-series data from records into a dict of lists."""
    streams = defaultdict(list)
    start_time = None

    for r in records:
        ts = r.get("timestamp")
        if ts:
            if start_time is None:
                start_time = ts
            elapsed = (ts - start_time).total_seconds()
            streams["time"].append(elapsed)
        else:
            streams["time"].append(len(streams["time"]) * 1.0)  # fallback: 1s intervals

        streams["heartrate"].append(r.get("heart_rate", r.get("heartrate", None)))
        streams["power"].append(r.get("power", r.get("watts", None)))
        streams["cadence"].append(r.get("cadence", None))
        streams["speed"].append(r.get("speed", r.get("enhanced_speed", None)))
        streams["altitude"].append(r.get("altitude", r.get("enhanced_altitude", None)))
        lat_v = r.get("position_lat", None); streams["lat"].append(lat_v * (180.0 / 2147483648.0) if lat_v is not None and abs(lat_v) > 180 else lat_v)
        lon_v = r.get("position_long", None); streams["lon"].append(lon_v * (180.0 / 2147483648.0) if lon_v is not None and abs(lon_v) > 180 else lon_v)

    return dict(streams)


def _compute_metrics_from_streams(streams, filepath, fmt):
    """Compute activity metrics from stream data."""
    now = datetime.now(timezone.utc)

    # Determine start/end from timestamps
    times = streams.get("time", [])
    start_time = now
    end_time = now

    # Distance from GPS
    distance = _compute_distance(streams)

    # Elevation
    elevations = [a for a in streams.get("altitude", []) if a is not None]
    elevation_gain = 0
    elevation_loss = 0
    if len(elevations) > 1:
        for i in range(1, len(elevations)):
            diff = elevations[i] - elevations[i - 1]
            if diff > 0:
                elevation_gain += diff
            else:
                elevation_loss += abs(diff)

    # Speed
    speeds = [s for s in streams.get("speed", []) if s is not None]
    avg_speed = (distance / times[-1]) if times and times[-1] > 0 else 0
    max_speed = max(speeds) if speeds else 0

    # Heart rate
    hrs = [h for h in streams.get("heartrate", []) if h is not None]
    avg_hr = sum(hrs) / len(hrs) if hrs else None
    max_hr = max(hrs) if hrs else None

    # Power
    powers = [p for p in streams.get("power", []) if p is not None]
    avg_power = sum(powers) / len(powers) if powers else None
    max_power = max(powers) if powers else None
    np = _normalized_power(powers) if len(powers) >= 30 else None

    # Cadence
    cads = [c for c in streams.get("cadence", []) if c is not None]
    avg_cad = sum(cads) / len(cads) if cads else None

    # Energy
    kj = sum(powers) * (times[-1] / len(powers)) / 1000 if powers and times else None
    # Calories ~ 1 kcal per kJ for cycling
    calories = kj * 1.0 if kj else None

    # Intensity Factor: NP / FTP (FTP defaults to a guess if unknown)
    # We'll store NP and let the frontend compute IF with user's FTP
    intensity_factor = None

    moving_time = _compute_moving_time(streams, distance)

    return {
        "name": os.path.splitext(os.path.basename(filepath))[0],
        "sport": "cycling" if "cycling" in filepath.lower() else "cycling",
        "start_time": start_time,
        "end_time": end_time,
        "source_file": filepath,
        "file_format": fmt,
        "distance_m": distance,
        "moving_time_s": moving_time,
        "elapsed_time_s": times[-1] if times else 0,
        "avg_speed_ms": avg_speed,
        "max_speed_ms": max_speed,
        "elevation_gain_m": elevation_gain,
        "elevation_loss_m": elevation_loss,
        "avg_elevation_m": sum(elevations) / len(elevations) if elevations else None,
        "max_elevation_m": max(elevations) if elevations else None,
        "min_elevation_m": min(elevations) if elevations else None,
        "avg_heartrate": avg_hr,
        "max_heartrate": max_hr,
        "avg_power_w": avg_power,
        "max_power_w": max_power,
        "normalized_power_w": np,
        "avg_cadence": avg_cad,
        "max_cadence": max(cads) if cads else None,
        "calories_kcal": round(calories) if calories else None,
        "kilojoules_kj": round(kj) if kj else None,
        "intensity_factor": intensity_factor,
    }


def _compute_distance(streams):
    """Compute total distance from lat/lon using Haversine."""
    import math

    lats = streams.get("lat", [])
    lons = streams.get("lon", [])
    valid = [(lats[i], lons[i]) for i in range(len(lats))
             if lats[i] is not None and lons[i] is not None]

    if len(valid) < 2:
        return 0

    total = 0
    for i in range(1, len(valid)):
        lat1, lon1 = valid[i - 1]
        lat2, lon2 = valid[i]
        # Haversine with domain error protection
        R = 6371000  # Earth radius in meters
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        a = max(0.0, min(1.0, a))  # clamp to avoid math domain error
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        total += R * c

    return total


def _compute_moving_time(streams, distance):
    """Estimate moving time by filtering out stopped periods."""
    # Simple: if speed is available, exclude periods with speed < 0.5 m/s
    speeds = streams.get("speed", [])
    times = streams.get("time", [])
    if len(speeds) < 2 or len(times) < 2:
        return times[-1] if times else 0

    moving = 0
    for i in range(1, len(times)):
        if speeds[i] is not None and speeds[i] >= 0.5:
            moving += times[i] - times[i - 1]
        elif speeds[i] is None and i < len(speeds) - 1:
            # Interpolate
            before = next((s for s in speeds[max(0, i - 5):i] if s is not None), None)
            after = next((s for s in speeds[i:min(len(speeds), i + 5)] if s is not None), None)
            if (before is not None and before >= 0.5) or (after is not None and after >= 0.5):
                moving += times[i] - times[i - 1]

    return max(moving, times[-1] * 0.5)  # At least 50% of elapsed


def _normalized_power(powers, window_s=30):
    """Compute Normalized Power (30s rolling average, then 4th power)."""
    if len(powers) < window_s:
        return None

    # 30-second rolling average
    rolling = []
    window = min(window_s, len(powers))
    for i in range(len(powers) - window + 1):
        avg = sum(powers[i:i + window]) / window
        rolling.append(avg)

    # 4th power average, then 4th root
    fourth_power_sum = sum(r ** 4 for r in rolling)
    np = (fourth_power_sum / len(rolling)) ** 0.25
    return np


def _build_geojson(streams):
    """Build a simplified GeoJSON LineString from streams."""
    lats = streams.get("lat", [])
    lons = streams.get("lon", [])
    coords = []
    for i in range(min(len(lats), len(lons))):
        if lats[i] is not None and lons[i] is not None:
            if abs(lats[i]) <= 90 and abs(lons[i]) <= 180:
                coords.append([lons[i], lats[i]])

    if not coords:
        return None

    # Simplify: keep every ~500 points max
    step = max(1, len(coords) // 500)
    coords = [coords[i] for i in range(0, len(coords), step)]

    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": coords,
        },
        "properties": {},
    }


def _process_lap(lap):
    """Convert a FIT lap message to our format."""
    return {
        "start_time": str(lap.get("start_time", "")),
        "end_time": str(lap.get("end_time", "")),
        "distance_m": lap.get("total_distance", lap.get("distance", 0)),
        "time_s": lap.get("total_timer_time", lap.get("timer_time", lap.get("total_elapsed_time", 0))),
        "avg_speed_ms": lap.get("enhanced_avg_speed", lap.get("avg_speed")),
        "max_speed_ms": lap.get("enhanced_max_speed", lap.get("max_speed")),
        "avg_heartrate": lap.get("avg_heart_rate"),
        "max_heartrate": lap.get("max_heart_rate"),
        "avg_power_w": lap.get("avg_power"),
        "max_power_w": lap.get("max_power"),
        "avg_cadence": lap.get("avg_cadence"),
        "elevation_gain_m": lap.get("total_ascent", 0),
        "elevation_loss_m": lap.get("total_descent", 0),
        "calories_kcal": lap.get("total_calories"),
    }


def _apply_session_data(result, session):
    """Override computed metrics with more accurate session-level data from FIT."""
    for field_map in [
        ("start_time", "start_time"),
        ("end_time", "end_time", "timestamp"),
        ("distance_m", "total_distance"),
        ("moving_time_s", "total_timer_time", "total_moving_time"),
        ("elapsed_time_s", "total_elapsed_time"),
        ("avg_speed_ms", "enhanced_avg_speed", "avg_speed"),
        ("max_speed_ms", "enhanced_max_speed", "max_speed"),
        ("elevation_gain_m", "total_ascent"),
        ("elevation_loss_m", "total_descent"),
        ("avg_heartrate", "avg_heart_rate"),
        ("max_heartrate", "max_heart_rate"),
        ("avg_power_w", "avg_power"),
        ("max_power_w", "max_power"),
        ("avg_cadence", "avg_cadence"),
        ("calories_kcal", "total_calories"),
    ]:
        target = field_map[0]
        for src in field_map[1:]:
            val = session.get(src)
            if val is not None:
                result[target] = val
                break

    # Sport
    sport_map = session.get("sport")
    if sport_map is not None:
        # Sport removed - deprecated import
        if isinstance(sport_map, str):
            result["sport"] = str(sport_map).lower()


def _empty_result(filepath, fmt):
    """Return a minimal result for unparseable files."""
    return {
        "name": os.path.splitext(os.path.basename(filepath))[0],
        "sport": "cycling",
        "start_time": datetime.now(timezone.utc),
        "end_time": datetime.now(timezone.utc),
        "file_format": fmt,
        "source_file": filepath,
        "distance_m": 0,
        "moving_time_s": 0,
        "elapsed_time_s": 0,
        "avg_speed_ms": 0,
        "max_speed_ms": 0,
        "elevation_gain_m": 0,
        "elevation_loss_m": 0,
        "avg_heartrate": None,
        "max_heartrate": None,
        "avg_power_w": None,
        "max_power_w": None,
        "normalized_power_w": None,
        "avg_cadence": None,
        "calories_kcal": None,
        "kilojoules_kj": None,
        "streams": {},
        "track_geojson": None,
    }
