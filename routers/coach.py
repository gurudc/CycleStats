from routers.auth import require_session
from fastapi import APIRouter, Depends, HTTPException
from database import get_db, CoachNote
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import json

router = APIRouter(prefix="/api/coach", tags=["coach"])

@router.get("/latest")
def get_latest_note(db: Session = Depends(get_db),         _session = Depends(require_session)):
    """Get the most recent coach note."""
    note = db.query(CoachNote).order_by(CoachNote.id.desc()).first()
    if not note:
        return {"note": None, "date": None}
    return {
        "id": note.id,
        "note": note.note,
        "date": note.date.isoformat() if note.date else None,
        "created_at": note.created_at.isoformat() if note.created_at else None,
    }

@router.get("/history")
def get_coach_history(limit: int = 10, db: Session = Depends(get_db),         _session = Depends(require_session)):
    """Get recent coach notes."""
    notes = db.query(CoachNote).order_by(CoachNote.id.desc()).limit(limit).all()
    return [{
        "id": n.id,
        "note": n.note,
        "date": n.date.isoformat() if n.date else None,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    } for n in notes]

@router.post("/note")
def create_coach_note(body: dict, db: Session = Depends(get_db),         _session = Depends(require_session)):
    """Save a coach note (called by the cron job)."""
    note_text = body.get("note", "")
    prompt_data = body.get("prompt_data", "")
    if not note_text:
        raise HTTPException(status_code=400, detail="Note text required")
    note = CoachNote(
        date=datetime.utcnow(),
        note=note_text,
        prompt_data=json.dumps(prompt_data) if isinstance(prompt_data, dict) else str(prompt_data),
    )
    db.add(note)
    db.commit()
    return {"success": True, "id": note.id}
