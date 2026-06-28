"""Wahoo integration routes — OAuth flow, sync control, status."""
import os
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session

from database import get_db, WahooAccount, init_db
from services import wahoo_client, wahoo_sync
from routers.auth import require_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/wahoo", tags=["wahoo"])

# Temporary storage for PKCE verifiers between auth steps
# In production, use a proper session store or Redis
_pkce_verifiers = {}


@router.get("/status")
def status(request: Request, db: Session = Depends(get_db), _session=Depends(require_session)):
    """Check Wahoo integration status."""
    configured = wahoo_client.is_configured()
    accounts = []
    if configured:
        accounts = wahoo_sync.get_sync_status(db)

    tunnel_url = None
    tunnel_active = False

    return {
        "configured": configured,
        "connected_accounts": len(accounts),
        "accounts": accounts,
        "auth_url": "/api/wahoo/auth-url",
        "callback_url": "/api/wahoo/callback",
        "tunnel_active": tunnel_active,
        "tunnel_url": tunnel_url,
    }


@router.get("/auth-url")
def get_auth_url(redirect_uri: str = None, _session=Depends(require_session), db: Session = Depends(get_db)):
    """Generate the Wahoo OAuth authorization URL."""
    if not wahoo_client.is_configured():
        raise HTTPException(
            status_code=400,
            detail="Wahoo API not configured. Set WAHOO_CLIENT_ID and WAHOO_CLIENT_SECRET in .env"
        )

    try:
        url, verifier, method, actual_redirect = wahoo_client.build_auth_url(redirect_uri)

        # Store verifier temporarily (keyed by hash of URL for retrieval)
        import hashlib
        key = hashlib.md5(url.encode()).hexdigest()
        _pkce_verifiers[key] = {"verifier": verifier, "method": method, "redirect_uri": actual_redirect}

        # Check tunnel status
        from services.tunnel import get_tunnel_url, is_available as tunnel_available
        tunnel_url = get_tunnel_url()

        return {
            "auth_url": url,
                "redirect_uri": actual_redirect,
            "tunnel_active": tunnel_url is not None,
            "tunnel_url": tunnel_url,
        }
    except Exception as e:
        logger.exception("Failed to build auth URL")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/callback")
def oauth_callback(
    code: str = Query(None),
    error: str = Query(None),
    error_description: str = Query(None),
    state: str = Query(None),
    db: Session = Depends(get_db),
):
    """Handle OAuth callback from Wahoo and exchange code for tokens."""
    if error:
        logger.warning(f"Wahoo auth error: {error} - {error_description}")
        return HTMLResponse(
            content=f"<html><body><h2>Authorization Failed</h2><p>{error}: {error_description}</p>"
            f"<p><a href='/'>Return to CycleStats</a></p></body></html>",
            status_code=400,
        )

    if not code:
        raise HTTPException(status_code=400, detail="No authorization code received")

    # Look up the code verifier. We need to guess the key or have the user provide it.
    # In a real app, this would come from session state. For simplicity, we try all stored keys.
    verifier = None
    for key, data in list(_pkce_verifiers.items()):
        verifier = data["verifier"]
        break  # Use the most recently stored one

    # No PKCE verifier needed - using client_secret OAuth2 flow
    try:
        result = wahoo_client.exchange_code(code)
    except Exception as e:
        logger.exception("Failed to exchange authorization code")
        return HTMLResponse(
            content=f"<html><body><h2>Token Exchange Failed</h2><p>{str(e)}</p>"
            f"<p><a href='/'>Return to CycleStats</a></p></body></html>",
            status_code=400,
        )

    # Get user info
    try:
        user_info = wahoo_client.get_user_info(result["access_token"])
    except Exception as e:
        logger.warning(f"Could not fetch user info: {e}")
        user_info = {}

    # Store account
    wahoo_user_id = str(user_info.get("id", result.get("user_id", "unknown")))
    expires_in = result.get("expires_in", 7200)

    existing = db.query(WahooAccount).filter(
        WahooAccount.wahoo_user_id == wahoo_user_id
    ).first()

    if existing:
        existing.access_token = result["access_token"]
        existing.refresh_token = result.get("refresh_token", result.get("refresh_token", existing.refresh_token))
        existing.token_expires_at = datetime.utcnow() + __import__('datetime').timedelta(seconds=expires_in)
        existing.is_active = 1
        existing.sync_enabled = 1
    else:
        account = WahooAccount(
            wahoo_user_id=wahoo_user_id,
            email=user_info.get("email", ""),
            first_name=user_info.get("first", ""),
            last_name=user_info.get("last", ""),
            access_token=result["access_token"],
            refresh_token=result.get("refresh_token", ""),
            token_expires_at=datetime.utcnow() + __import__('datetime').timedelta(seconds=expires_in),
            scopes=" ".join(wahoo_client.REQUIRED_SCOPES),
        )
        db.add(account)

    db.commit()

    # Trigger initial sync
    try:
        from services.wahoo_sync import sync_account
        account = db.query(WahooAccount).filter(
            WahooAccount.wahoo_user_id == wahoo_user_id
        ).first()
        if account:
            # Fire and forget — run in background
            import threading
            t = threading.Thread(target=_sync_in_thread, args=(account.id,), daemon=True)
            t.start()
    except Exception as e:
        logger.warning(f"Initial sync trigger failed: {e}")

    # Clean up verifier
    _pkce_verifiers.clear()

    return HTMLResponse(
        content="<html><body style='font-family:sans-serif;background:#0f1117;color:#e4e6ef;"
        "display:flex;align-items:center;justify-content:center;height:100vh;text-align:center;'>"
        "<div><h1 style='color:#34d399;'>✅ Wahoo Connected!</h1>"
        "<p style='color:#8b8fa3;margin:16px 0;'>Your Wahoo account is linked. Activities will sync automatically.</p>"
        "<p style='color:#8b8fa3;'>Return to CycleStats to see your imported workouts.</p>"
        "<p style='margin-top:24px;'><a href='/' style='color:#6366f1;'>← Back to Dashboard</a></p>"
        "</div></body></html>"
    )


def _sync_in_thread(account_id):
    """Run sync in a background thread."""
    db = next(get_db())
    try:
        account = db.query(WahooAccount).filter(WahooAccount.id == account_id).first()
        if account:
            wahoo_sync.sync_account(account, db)
    except Exception as e:
        logger.error(f"Background sync failed: {e}")
    finally:
        db.close()


@router.post("/sync")
def trigger_sync(request: Request, db: Session = Depends(get_db), _session=Depends(require_session)):
    """Manually trigger a sync for all connected Wahoo accounts."""
    if not wahoo_client.is_configured():
        raise HTTPException(status_code=400, detail="Wahoo API not configured")

    results = wahoo_sync.sync_all_accounts(db)
    return {
        "message": "Sync complete",
        "results": results,
    }


@router.post("/disconnect/{account_id}")
def disconnect(request: Request, account_id: int, db: Session = Depends(get_db), _session=Depends(require_session)):
    """Disconnect a Wahoo account."""
    success = wahoo_sync.disconnect_account(account_id, db)
    if not success:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"message": "Account disconnected"}


@router.get("/setup-instructions")
def setup_instructions():
    """Get instructions for setting up Wahoo API credentials."""
    return {
        "steps": [
            "1. Go to https://developers.wahooligan.com and create an account",
            "2. Create a new application (choose 'Sandbox' for testing)",
            "3. ⚠️ Wahoo requires HTTPS for OAuth redirect. Set Redirect URI to the HTTPS URL from the methods below",
            "4. Enable scopes: user_read, workouts_read, offline_data",
            "5. Copy your Client ID and Client Secret",
            "6. Set environment variables below and restart with HTTPS",
        ],
        "env_vars": {
            "WAHOO_CLIENT_ID": "your_client_id_here",
            "WAHOO_CLIENT_SECRET": "your_client_secret_here",
        },
        "https_options": [
            {
                "name": "Option A: ngrok tunnel (easiest)",
                "steps": [
                    "Run: pip install pyngrok",
                    "Run: cd ~/cyclestats && python scripts/tunnel.py",
                    "Copy the ngrok HTTPS URL shown in the terminal",
                    "Set that as your Redirect URI in the Wahoo developer portal",
                ],
                "env_vars": {
                    "WAHOO_REDIRECT_URI": "https://your-ngrok-url.ngrok.io/api/wahoo/callback",
                },
            },
            {
                "name": "Option B: Self-signed HTTPS (no external service)",
                "steps": [
                    "Run: cd ~/cyclestats && python scripts/generate_ssl_cert.py",
                    "Set CYCLESTATS_HTTPS=1 and start: cd backend && CYCLESTATS_HTTPS=1 python main.py",
                    "In your browser, click Advanced → Proceed to localhost (unsafe)",
                    "Set Redirect URI in Wahoo developer portal to: https://localhost:8080/api/wahoo/callback",
                ],
                "env_vars": {
                    "CYCLESTATS_HTTPS": "1",
                    "WAHOO_REDIRECT_URI": "https://localhost:8080/api/wahoo/callback",
                },
            },
        ],
        "config_methods": [
            "Option A: Add to ~/cyclestats/.env file",
            "Option B: Export in terminal before starting:",
            "  export WAHOO_CLIENT_ID=xxx",
            "  export WAHOO_CLIENT_SECRET=xxx",
            "  export WAHOO_REDIRECT_URI=http://127.0.0.1:8080/api/wahoo/callback",
            "",
            "HTTPS NOTE: Wahoo requires HTTPS for OAuth redirect URIs.",
            "When you click 'Connect Wahoo', a secure ngrok tunnel is auto-started.",
            "Use the displayed HTTPS URL as the redirect URI in the Wahoo Developer Portal.",
        ],
    }
