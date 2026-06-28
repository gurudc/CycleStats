"""HTTPS tunnel manager — creates a public ngrok URL for Wahoo OAuth redirect.

This solves the problem that Wahoo's OAuth requires HTTPS redirect URIs
while our dev server runs on HTTP localhost.
"""
import os
import json
import time
import logging
import subprocess
import threading
import urllib.request

logger = logging.getLogger(__name__)

# Path to ngrok (installed by Hermes or system)
NGROK_PATH = None
for candidate in [
    os.path.expanduser("~/AppData/Local/hermes/hermes-agent/venv/Scripts/ngrok"),
    os.path.expanduser("~/AppData/Local/hermes/hermes-agent/venv/bin/ngrok"),
    "/usr/local/bin/ngrok",
    "/nonexistent/dwcol/AppData/Local/hermes/hermes-agent/venv/Scripts/ngrok",
]:
    if os.path.exists(candidate):
        NGROK_PATH = candidate
        break

_tunnel_process = None
_tunnel_url = None
_tunnel_lock = threading.Lock()


def _find_ngrok():
    """Find ngrok executable."""
    if NGROK_PATH:
        return NGROK_PATH
    # Try PATH
    try:
        result = subprocess.run(["where", "ngrok" if os.name == "nt" else "which", "ngrok"],
                               capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            path = result.stdout.strip().split("\n")[0].strip()
            if path:
                return path
    except Exception:
        pass
    return None


def is_available():
    """Check if ngrok is installed."""
    return _find_ngrok() is not None


def start_tunnel(port=8080):
    """Start an ngrok HTTP tunnel to the given port.

    Returns the public HTTPS URL, or None on failure.
    """
    global _tunnel_process, _tunnel_url

    with _tunnel_lock:
        if _tunnel_url:
            return _tunnel_url

        ngrok_path = _find_ngrok()
        if not ngrok_path:
            logger.error("ngrok not found. Install from https://ngrok.com/download")
            return None

        logger.info(f"Starting ngrok tunnel to port {port}...")

        try:
            proc = subprocess.Popen(
                [ngrok_path, "http", str(port), "--log=stdout", "--log-format=json"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            _tunnel_process = proc
        except Exception as e:
            logger.error(f"Failed to start ngrok: {e}")
            return None

        # Wait for the API to be ready
        ngrok_api = "http://127.0.0.1:4040/api/tunnels"
        for attempt in range(20):
            time.sleep(1)
            try:
                resp = urllib.request.urlopen(ngrok_api, timeout=3)
                data = json.loads(resp.read().decode())
                tunnels = data.get("tunnels", [])
                for t in tunnels:
                    if t.get("proto") == "https":
                        url = t["public_url"]
                        _tunnel_url = url
                        logger.info(f"ngrok tunnel ready: {url}")
                        return url
            except Exception:
                continue

        logger.error("ngrok tunnel failed to start within 20s")
        stop_tunnel()
        return None


def stop_tunnel():
    """Stop the ngrok tunnel."""
    global _tunnel_process, _tunnel_url

    with _tunnel_lock:
        if _tunnel_process:
            try:
                _tunnel_process.terminate()
                _tunnel_process.wait(timeout=5)
            except Exception:
                _tunnel_process.kill()
            _tunnel_process = None
        _tunnel_url = None
        logger.info("ngrok tunnel stopped")


def get_tunnel_url():
    """Get the current tunnel URL, or None."""
    return _tunnel_url


def get_redirect_uri():
    """Get the HTTPS redirect URI for Wahoo OAuth callback."""
    tunnel_url = get_tunnel_url()
    if tunnel_url:
        return f"{tunnel_url}/api/wahoo/callback"
    # Default to HTTPS with self-signed cert
    return os.getenv("WAHOO_REDIRECT_URI", "https://127.0.0.1:8080/api/wahoo/callback")
