import logging; logger = logging.getLogger(__name__)
from routers.auth import require_session
# Segments router - Strava-style segments with auto-detection
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
import math
import json
import traceback

from database import get_db, Activity

router = APIRouter(prefix="/api/segments", tags=["segments"])

SEGMENTS = []

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def cluster_points(points, threshold=0.01):
    """Cluster nearby GPS points (larger threshold for routes)."""
    clusters = []
    for lat, lng in points:
        found = False
        for cluster in clusters:
            center_lat, center_lng = cluster['center']
            if abs(lat - center_lat) < threshold and abs(lng - center_lng) < threshold:
                cluster['points'].append((lat, lng))
                n = len(cluster['points'])
                cluster['center'] = (center_lat * (n-1)/n + lat/n, center_lng * (n-1)/n + lng/n)
                found = True
                break
        if not found:
            clusters.append({'points': [(lat, lng)], 'center': (lat, lng)})
    return clusters

@router.get("/", response_model=List[dict])
def list_segments(_session = Depends(require_session)):
    return SEGMENTS

@router.post("/auto-detect")
def auto_detect_segments(db: Session = Depends(get_db), min_occurrences: int = 2,         _session = Depends(require_session)):
    """Auto-detect segments from activity start/end points."""
    global SEGMENTS
    try:
        activities = db.query(Activity).all()
        
        # Collect all start/end pairs
        routes = {}
        
        for act in activities:
            coords = None
            if act.streams:
                try:
                    s = act.streams
                    # Handle both Strava format (latlng.data) and transformed format (lat/lon arrays)
                    if isinstance(s.get('latlng'), dict) and 'data' in s['latlng']:
                        raw = s['latlng']['data']
                        coords = [(p[1], p[0]) for p in raw if len(p) >= 2]  # lon, lat format
                    elif s.get('lat') and s.get('lon'):
                        lat_arr = s['lat']
                        lon_arr = s['lon']
                        if isinstance(lat_arr, dict) and 'data' in lat_arr:
                            lat_arr = lat_arr['data']
                        if isinstance(lon_arr, dict) and 'data' in lon_arr:
                            lon_arr = lon_arr['data']
                        coords = [(lon_arr[i], lat_arr[i]) for i in range(min(len(lat_arr), len(lon_arr)))]
                except:
                    pass
            
            if not coords or len(coords) < 10:
                continue
            
            # Get start and end points
            start_lat, start_lng = coords[0][1], coords[0][0]
            end_lat, end_lng = coords[-1][1], coords[-1][0]
            
            # Create a route key (start -> end)
            # Round to ~100m precision
            key = f"{round(start_lat,3)}:{round(start_lng,3)}->{round(end_lat,3)}:{round(end_lng,3)}"
            
            if key not in routes:
                routes[key] = {'start': (start_lat, start_lng), 'end': (end_lat, end_lng), 'count': 0}
            routes[key]['count'] += 1
        
        # Find routes that appear multiple times
        threshold = 0.003  # ~300m
        new_segments = []
        
        for key, route in routes.items():
            if route['count'] >= min_occurrences:
                start_lat, start_lng = route['start']
                end_lat, end_lng = route['end']
                
                distance = haversine(start_lat, start_lng, end_lat, end_lng)
                
                # Skip very short or very long routes
                if distance < 1000 or distance > 50000:
                    continue
                
                # Check if similar segment exists
                exists = False
                for s in SEGMENTS:
                    if (abs(s['start_lat'] - start_lat) < 0.01 and 
                        abs(s['end_lat'] - end_lat) < 0.01):
                        exists = True
                        break
                
                if not exists:
                    new_id = max([s['id'] for s in SEGMENTS], default=0) + 1
                    segment = {
                        'id': new_id,
                        'name': f"Route {new_id}",
                        'sport': 'cycling',
                        'start_lat': start_lat,
                        'start_lng': start_lng,
                        'end_lat': end_lat,
                        'end_lng': end_lng,
                        'distance_m': int(distance),
                        'occurrences': route['count']
                    }
                    SEGMENTS.append(segment)
                    new_segments.append(segment)
        
        return {'detected': len(new_segments), 'segments': new_segments}
    except Exception as e:
        traceback.print_exc()
        return {'error': str(e)}

@router.get("/{segment_id}/leaderboard")
def get_leaderboard(segment_id: int, db: Session = Depends(get_db),         _session = Depends(require_session)):
    segment = next((s for s in SEGMENTS if s['id'] == segment_id), None)
    if not segment:
        return {"segment": None, "results": []}
    
    activities = db.query(Activity).all()
    
    results = []
    for act in activities:
        coords = None
        if act.track_geojson:
            try:
                if isinstance(act.track_geojson, str):
                    geojson = json.loads(act.track_geojson)
                else:
                    geojson = act.track_geojson
                if geojson and 'geometry' in geojson:
                    coords = geojson['geometry'].get('coordinates', [])
            except:
                pass
        
        if not coords:
            continue
            
        # Check if activity passes through segment area
        in_segment = False
        for coord in coords:
            if len(coord) >= 2:
                lat, lng = coord[1], coord[0]
                if (min(segment['start_lat'], segment['end_lat']) - 0.005 <= lat <= max(segment['start_lat'], segment['end_lat']) + 0.005 and
                    min(segment['start_lng'], segment['end_lng']) - 0.005 <= lng <= max(segment['start_lng'], segment['end_lng']) + 0.005):
                    in_segment = True
                    break
        
        if in_segment:
            results.append({
                "activity_id": act.id,
                "activity_name": act.name,
                "date": act.start_time.isoformat() if act.start_time else None,
                "time_s": act.elapsed_time_s or 0,
                "distance_m": act.distance_m or 0,
                "avg_power": None
            })
    
    results.sort(key=lambda x: x['time_s'] if x['time_s'] else float('inf'))
    return {"segment": segment, "results": results[:10]}

@router.post("/")
def create_segment(name: str, sport: str = "cycling", start_lat: float = 0, start_lng: float = 0, 
                  end_lat: float = 0, end_lng: float = 0, distance_m: float = 0,         _session = Depends(require_session)):
    global SEGMENTS
    new_id = max([s['id'] for s in SEGMENTS], default=0) + 1
    segment = {
        "id": new_id,
        "name": name,
        "sport": sport,
        "start_lat": start_lat,
        "start_lng": start_lng,
        "end_lat": end_lat,
        "end_lng": end_lng,
        "distance_m": distance_m
    }
    SEGMENTS.append(segment)
    return segment

@router.delete("/{segment_id}")
def delete_segment(segment_id: int,         _session = Depends(require_session)):
    global SEGMENTS
    SEGMENTS = [s for s in SEGMENTS if s['id'] != segment_id]
    return {"success": True}