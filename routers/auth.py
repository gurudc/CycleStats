from fastapi import APIRouter, Request, Response, Depends, HTTPException
from pydantic import BaseModel
import os, hashlib, logging, crypt
from datetime import datetime, timezone, timedelta
## passlib removed
from fastapi import HTTPException
from datetime import datetime, timezone, timedelta
import json, os


router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)
## passlib removed

AUTH_PASSWORD_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "auth_password.txt",
)

COOKIE_NAME = "cyclestats_session"
SESSION_DURATION_HOURS = 24


def _load_password() -> str:
    try:
        return open(AUTH_PASSWORD_FILE).read().strip()
    except Exception:
        return ""


def _generate_token() -> str:
    return hashlib.sha256(os.urandom(64)).hexdigest()


def get_current_session(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "bearer"})
    store_path = "/opt/cyclestats/backend/data/auth_sessions.json"
    try:
        data = json.load(open(store_path))
    except Exception:
        data = {}
    rec = data.get(token)
    if not rec:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    if datetime.fromisoformat(rec["expires_at"]) < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session expired")
    return rec


class LoginRequest(BaseModel):
    username: str | None = None
    password: str


@router.post("/login")
def login(
    response: Response,
    body: LoginRequest,
):
    stored_password = _load_password()
    if not stored_password or crypt.crypt(body.password, stored_password) != stored_password:
        raise HTTPException(status_code=401, detail="Invalid password")

    token = _generate_token()
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=SESSION_DURATION_HOURS)).isoformat()

    # Save session to file
    store_path = "/opt/cyclestats/backend/data/auth_sessions.json"
    try:
        import json as j
        with open(store_path) as f:
            sessions = j.load(f)
    except Exception:
        sessions = {}
    sessions[token] = {"token": token, "username": body.username or "admin", "expires_at": expires_at}
    with open(store_path, "w") as f:
        j.dump(sessions, f)

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
        max_age=SESSION_DURATION_HOURS * 3600,
    )
    return {"success": True, "token": token}


@router.get("/check")
def check_session(
    session = Depends(get_current_session),
):
    return {
        "authenticated": True,
        "session_id": session.id,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "expires_at": session.expires_at.isoformat() if session.expires_at else None,
    }


@router.get("/logout")
def logout(
    response: Response,
    request: Request,
):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        store_path = "/opt/cyclestats/backend/data/auth_sessions.json"
        try:
            import json as j
            with open(store_path) as f:
                sessions = j.load(f)
            if token in sessions:
                del sessions[token]
            with open(store_path, "w") as f:
                j.dump(sessions, f)
        except Exception:
            pass
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return {"success": True, "message": "Logged out"}


def require_session(request: Request):
    return get_current_session(request)
