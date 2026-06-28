import requests
import time
import json
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

class StravaClient:
    def __init__(self, client_id: str, client_secret: str, state_path: str = "/opt/cyclestats/backend/data/strava_state.json"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.state_path = state_path
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.expires_at: Optional[int] = None
        self.load_state()

    def load_state(self):
        try:
            with open(self.state_path, 'r') as f:
                state = json.load(f)
                self.access_token = state.get("access_token")
                self.refresh_token = state.get("refresh_token")
                self.expires_at = state.get("expires_at")
        except FileNotFoundError:
            logger.warning("Strava state file not found.")

    def save_state(self):
        state = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at
        }
        with open(self.state_path, 'w') as f:
            json.dump(state, f)

    def refresh_token_if_needed(self):
        if self.expires_at and time.time() < self.expires_at - 300:
            return

        if not self.refresh_token:
            raise Exception("No refresh token available")

        resp = requests.post("https://www.strava.com/api/v3/oauth/token", data={
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token
        })
        
        if resp.status_code != 200:
            raise Exception(f"Failed to refresh token: {resp.text}")

        data = resp.json()
        self.access_token = data["access_token"]
        self.refresh_token = data["refresh_token"]
        self.expires_at = data["expires_at"]
        self.save_state()

    def get_headers(self) -> Dict[str, str]:
        self.refresh_token_if_needed()
        return {"Authorization": f"Bearer {self.access_token}"}

    def get_activities(self, limit: int = 50, page: int = 1) -> List[Dict[str, Any]]:
        headers = self.get_headers()
        resp = requests.get(
            "https://www.strava.com/api/v3/athlete/activities",
            headers=headers,
            params={"per_page": limit, "page": page}
        )
        resp.raise_for_status()
        return resp.json()

    def get_streams(self, activity_id: int) -> Dict[str, Any]:
        headers = self.get_headers()
        resp = requests.get(
            f"https://www.strava.com/api/v3/activities/{activity_id}/streams",
            headers=headers,
            params={"keys": "time,latlng,altitude,heartrate,cadence,watts,distance", "key_by_type": "true"}
        )
        if resp.status_code == 200:
            return resp.json()
        return {}
    def get_starred_segments(self) -> List[Dict[str, Any]]:
        headers = self.get_headers()
        resp = requests.get(
            "https://www.strava.com/api/v3/segments/starred",
            headers=headers
        )
        if resp.status_code == 200:
            return resp.json()
        logger.warning(f"Failed to get starred segments: {resp.status_code} {resp.text}")
        return []

    def get_segment_leaderboard(self, segment_id: int) -> Dict[str, Any]:
        headers = self.get_headers()
        resp = requests.get(
            f"https://www.strava.com/api/v3/segments/{segment_id}/leaderboard",
            headers=headers,
            params={"per_page": 10}
        )
        if resp.status_code == 200:
            return resp.json()
        logger.warning(f"Failed to get segment leaderboard: {resp.status_code}")
        return {}
    def get_auth_url(self, redirect_uri: str) -> str:
        return (
            f"https://www.strava.com/oauth/authorize"
            f"?client_id={self.client_id}"
            f"&redirect_uri={redirect_uri}"
            f"&response_type=code"
            f"&approval_prompt=auto"
            f"&scope=read,activity:read_all"
        )

    def exchange_code(self, code: str, redirect_uri: str) -> dict:
        resp = requests.post("https://www.strava.com/oauth/token", data={
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
        })
        if resp.status_code != 200:
            raise Exception(f"Token exchange failed: {resp.text}")
        data = resp.json()
        self.access_token = data["access_token"]
        self.refresh_token = data["refresh_token"]
        self.expires_at = data["expires_at"]
        self.save_state()
        return data

    def get_athlete(self) -> dict:
        headers = self.get_headers()
        resp = requests.get("https://www.strava.com/api/v3/athlete", headers=headers)
        if resp.status_code == 200:
            return resp.json()
        return {}
