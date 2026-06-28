"""HTTPS support for CycleStats using self-signed SSL certificate.

Generates cert if missing, provides SSL context for FastAPI/uvicorn.
Wahoo accepts self-signed certs for OAuth redirects.
"""
import os
import ssl
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CERTS_DIR = Path(__file__).parent.parent / "certs"
CERT_FILE = CERTS_DIR / "cert.pem"
KEY_FILE = CERTS_DIR / "key.pem"


def ensure_certs():
    """Ensure SSL certificates exist. Generate self-signed if missing."""
    CERTS_DIR.mkdir(exist_ok=True)

    if CERT_FILE.exists() and KEY_FILE.exists():
        logger.info("SSL certificates found")
        return True

    logger.info("Generating self-signed SSL certificate...")
    try:
        import subprocess
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", str(KEY_FILE),
            "-out", str(CERT_FILE),
            "-days", "365", "-nodes",
            "-subj", "//CN=localhost",
            "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
        ], check=True, capture_output=True, timeout=30)
        logger.info(f"Certificate generated: {CERT_FILE}")
        return True
    except Exception as e:
        logger.error(f"Failed to generate certificate: {e}")
        return False


def get_ssl_context():
    """Get SSL context for uvicorn."""
    if not CERT_FILE.exists() or not KEY_FILE.exists():
        if not ensure_certs():
            return None

    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(str(CERT_FILE), str(KEY_FILE))
    # Don't verify client certs (we're not asking for them)
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def get_https_url(port=8443):
    """Get the HTTPS URL for the app."""
    return f"https://127.0.0.1:{port}"


def get_https_redirect_uri(port=8443):
    """Get the HTTPS redirect URI for Wahoo OAuth callback."""
    return f"https://127.0.0.1:{port}/api/wahoo/callback"
