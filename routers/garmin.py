"""Garmin integration routes."""
import logging, os, subprocess, time
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db
from services import garmin_client, garmin_sync
from routers.auth import require_session

from routers.auth import require_session


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/garmin", tags=["garmin"])


@router.get("/status")
def get_status(request: Request, _session=Depends(require_session)):
    return {
        "available": garmin_client.is_available(),
        "configured": garmin_client.is_configured(),
        "email": None,
    }


@router.post("/status")
def save_credentials(email: str = None, password: str = None, _session=Depends(require_session)):
    """Save Garmin credentials to systemd and restart service."""
    email = email or os.getenv("GARMIN_EMAIL", "")
    password = password or os.getenv("GARMIN_PASSWORD", "")
    if not email or not password:
        return {"error": "Email and password required"}
    try:
        override_dir = "/etc/systemd/system/cyclestats.service.d"
        os.makedirs(override_dir, exist_ok=True)
        with open(os.path.join(override_dir, "garmin.conf"), "w") as f:
            f.write("[Service]\n")
            f.write(f"Environment=GARMIN_EMAIL={email}\n")
            f.write(f"Environment=GARMIN_PASSWORD=***\n")
        subprocess.run(["systemctl", "daemon-reload"], capture_output=True, timeout=10)
        subprocess.run(["systemctl", "restart", "cyclestats"], capture_output=True, timeout=15)
        time.sleep(3)
        return {"success": True, "message": "Credentials saved! Service restarted."}
    except Exception as e:
        return {"error": str(e)}


@router.post("/sync")
def trigger_sync(health_only: bool = False, db: Session = Depends(get_db), _session=Depends(require_session)):
    if not garmin_client.is_available():
        raise HTTPException(status_code=400, detail="garminconnect library not installed")
    if not garmin_client.is_configured():
        raise HTTPException(status_code=400, detail="Garmin credentials not set")
    if health_only:
        result = garmin_sync.sync_health_only(db)
    else:
        result = garmin_sync.sync_all(db)
    return {"message": "Garmin sync complete", "result": result}


@router.get("/setup-instructions")
def setup_instructions():
    return {
        "steps": [
            "1. Get your Garmin Connect email and password",
            "2. Add to your .env file or set environment variables:",
        ],
        "env_vars": {
            "GARMIN_EMAIL": "your_garmin_email",
            "GARMIN_PASSWORD": "your_garmin_password",
        },
        "warning": "For security, create an app password at https://connect.garmin.com if you use 2FA.",
    }
