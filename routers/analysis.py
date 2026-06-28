
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db, Activity
from services.power_duration import estimate_ftp, compute_mmp_curve

router = APIRouter(prefix='/api/analysis', tags=['analysis'])

def build_zones(ftp):
    return [
        {'label': 'Z1', 'name': 'Active Recovery', 'min': 0, 'max': 0.55},
        {'label': 'Z2', 'name': 'Endurance', 'min': 0.55, 'max': 0.75},
        {'label': 'Z3', 'name': 'Tempo', 'min': 0.75, 'max': 0.90},
        {'label': 'Z4', 'name': 'Threshold', 'min': 0.90, 'max': 1.05},
        {'label': 'Z5', 'name': 'VO2Max', 'min': 1.05, 'max': 1.20},
        {'label': 'Z6', 'name': 'Anaerobic Capacity', 'min': 1.20, 'max': 1.50},
        {'label': 'Z7', 'name': 'Neuromuscular', 'min': 1.50, 'max': 999}
    ]

@router.get('/{activity_id}')
def activity_analysis(activity_id: int, db: Session = Depends(get_db)):
    activity = db.query(Activity).filter(Activity.id == activity_id).first()
    if not activity or not activity.streams:
        return {'zones': [], 'intervals': []}
    
    all_ids = [a.id for a in db.query(Activity.id).all()]
    mmp = compute_mmp_curve(all_ids, db)
    ftp = estimate_ftp(mmp) or 200
    
    powers = activity.streams.get('power', [])
    times = activity.streams.get('time', [])
    
    zones = build_zones(ftp)
    zone_time = {z['label']: 0 for z in zones}
    for p in powers:
        if p is None: continue
        val = p / ftp
        for z in zones:
            if z['min'] <= val < z['max']:
                zone_time[z['label']] += 1
                break
    
    intervals = []
    current_interval = None
    for i, p in enumerate(powers):
        if p and p > ftp * 0.9:
            if not current_interval:
                current_interval = {'start': times[i], 'power': [p]}
            else:
                current_interval['power'].append(p)
        else:
            if current_interval and len(current_interval['power']) > 30:
                avg_p = sum(current_interval['power']) / len(current_interval['power'])
                intervals.append({'start': current_interval['start'], 'duration': len(current_interval['power']), 'avg_power': round(avg_p)})
            current_interval = None
            
    return {'zones': zone_time, 'intervals': intervals}
