"""Gear tracking router."""
from routers.auth import require_session
from database import Gear, Activity
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from datetime import datetime

router = APIRouter(tags=["gear"])

@router.get("/")
def list_gear(db: Session = Depends(get_db)):
    items = db.query(Gear).order_by(Gear.type, Gear.name).all()
    result = []
    for g in items:
        d = g.to_dict()
        total = db.query(db.func.sum(Activity.distance_m)).filter(Activity.gear_id == g.id).scalar() or 0
        d["current_mileage_km"] = round((g.start_mileage_km or 0) + total / 1000, 1)
        d["remaining_km"] = round(max(0, (g.replacement_mileage_km or 0) - d["current_mileage_km"]), 1) if g.replacement_mileage_km else None
        d["pct_used"] = round(d["current_mileage_km"] / g.replacement_mileage_km * 100, 1) if g.replacement_mileage_km and d["current_mileage_km"] > 0 else 0
        result.append(d)
    return result

@router.get("/types")
def gear_types():
    return {"types": ["shoes", "chain", "cassette", "tyres", "bike", "pedals", "wheels", "other"]}

@router.post("/")
def create_gear(body: dict, db: Session = Depends(get_db), _session=Depends(require_session)):
    g = Gear(name=body.get("name",""), type=body.get("type","other"), brand=body.get("brand",""),
        model=body.get("model",""), purchase_date=body.get("purchase_date"),
        start_mileage_km=body.get("start_mileage_km",0), replacement_mileage_km=body.get("replacement_mileage_km",0),
        notes=body.get("notes",""))
    db.add(g); db.commit(); db.refresh(g)
    return g.to_dict()

@router.patch("/{gear_id}")
def update_gear(gear_id: int, body: dict, db: Session = Depends(get_db), _session=Depends(require_session)):
    g = db.query(Gear).filter(Gear.id == gear_id).first()
    if not g: raise HTTPException(404)
    for k in ["name","type","brand","model","purchase_date","start_mileage_km","replacement_mileage_km","notes"]:
        if k in body: setattr(g, k, body[k])
    db.commit(); db.refresh(g)
    return g.to_dict()

@router.delete("/{gear_id}")
def delete_gear(gear_id: int, db: Session = Depends(get_db), _session=Depends(require_session)):
    g = db.query(Gear).filter(Gear.id == gear_id).first()
    if not g: raise HTTPException(404)
    db.query(Activity).filter(Activity.gear_id == gear_id).update({"gear_id": None})
    db.delete(g); db.commit()
    return {"success": True}

@router.patch("/activity/{activity_id}/gear")
def set_activity_gear(activity_id: int, body: dict, db: Session = Depends(get_db), _session=Depends(require_session)):
    a = db.query(Activity).filter(Activity.id == activity_id).first()
    if not a: raise HTTPException(404)
    a.gear_id = body.get("gear_id")
    db.commit()
    return {"success": True}
