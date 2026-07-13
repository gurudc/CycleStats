"""Database setup and session management."""
import os
from datetime import datetime
from sqlalchemy import Date, create_engine, Column, Integer, Float, String, Text, DateTime, JSON, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cyclestats.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# Allow PostgreSQL via DATABASE_URL env var, fall back to SQLite
import os as _db_os
_default_url = f"sqlite:///{DB_PATH}"
SQLALCHEMY_DATABASE_URL = _db_os.environ.get("DATABASE_URL", _default_url)
if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_size=10, max_overflow=20)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Activity(Base):
    __tablename__ = "activities"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), default="")
    sport = Column(String(50), default="cycling")  # cycling, running, etc.
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime)
    timezone = Column(String(50), default="UTC")

    # File info
    source_file = Column(String(500))
    file_format = Column(String(10))  # fit, gpx, tcx

    # Distances (meters)
    distance_m = Column(Float, default=0)

    # Time (seconds)
    moving_time_s = Column(Float, default=0)
    elapsed_time_s = Column(Float, default=0)

    # Speed (m/s)
    avg_speed_ms = Column(Float, default=0)
    max_speed_ms = Column(Float, default=0)

    # Elevation (meters)
    elevation_gain_m = Column(Float, default=0)
    elevation_loss_m = Column(Float, default=0)
    avg_elevation_m = Column(Float)
    max_elevation_m = Column(Float)
    min_elevation_m = Column(Float)

    # Heart rate (bpm)
    avg_heartrate = Column(Float)
    max_heartrate = Column(Float)
    min_heartrate = Column(Float)

    # Power (watts)
    avg_power_w = Column(Float)
    max_power_w = Column(Float)
    normalized_power_w = Column(Float)
    avg_weighted_power_w = Column(Float)
    intensity_factor = Column(Float)

    # Cadence (rpm)
    avg_cadence = Column(Float)
    max_cadence = Column(Float)

    # Energy
    calories_kcal = Column(Float)
    kilojoules_kj = Column(Float)

    # Training metrics
    tss = Column(Float)  # Training Stress Score
    xss = Column(Float)  # Xert Stress Score (if available)
    if_val = Column(Float)  # Intensity Factor
    pwi = Column(Float)  # Power Stress Score equivalent

    # GPS track (GeoJSON)
    track_geojson = Column(JSON)

    # Lap data (JSON array)
    laps = Column(JSON)

    # Streams (sampled data points)
    streams = Column(JSON)  # {time: [], heartrate: [], power: [], cadence: [], speed: [], altitude: [], lat: [], lon: []}

    # Weather (optional)
    weather = Column(JSON)
    ai_insight = Column(Text)
    notes = Column(Text, default="")

    # Gear
    gear_id = Column(Integer, ForeignKey("gear.id"))

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self, include_streams=False):
        d = {
            "id": self.id,
            "name": self.name,
            "sport": self.sport,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "distance_km": round(self.distance_m / 1000, 2) if self.distance_m else 0,
            "moving_time": self._fmt_time(self.moving_time_s),
            "moving_time_s": self.moving_time_s,
            "elapsed_time_s": self.elapsed_time_s,
            "avg_speed_kmh": round(self.avg_speed_ms * 3.6, 1) if self.avg_speed_ms else 0,
            "max_speed_kmh": round(self.max_speed_ms * 3.6, 1) if self.max_speed_ms else 0,
            "elevation_gain_m": round(self.elevation_gain_m, 0) if self.elevation_gain_m else 0,
            "avg_heartrate": round(self.avg_heartrate) if self.avg_heartrate else None,
            "max_heartrate": round(self.max_heartrate) if self.max_heartrate else None,
            "avg_power_w": round(self.avg_power_w) if self.avg_power_w else None,
            "max_power_w": round(self.max_power_w) if self.max_power_w else None,
            "normalized_power_w": round(self.normalized_power_w) if self.normalized_power_w else None,
            "avg_cadence": round(self.avg_cadence) if self.avg_cadence else None,
            "calories_kcal": round(self.calories_kcal) if self.calories_kcal else None,
            "kilojoules_kj": round(self.kilojoules_kj) if self.kilojoules_kj else None,
            "tss": round(self.tss, 1) if self.tss else None,
            "intensity_factor": round(self.intensity_factor, 2) if self.intensity_factor else None,
            "track_geojson": self.track_geojson,
            "ai_insight": self.ai_insight,
            "notes": self.notes or "",
            "gear_id": self.gear_id,
        }
        if include_streams and self.streams:
            # Transform Strava streams to frontend format
            s = self.streams
            time_data = s.get('time', {}).get('data', []) if isinstance(s.get('time'), dict) else s.get('time', [])
            dist_data = s.get('distance', {}).get('data', []) if isinstance(s.get('distance'), dict) else s.get('distance', [])
            # Compute speed from distance + time
            speed_data = [0.0]
            for si in range(1, min(len(dist_data), len(time_data))):
                d_diff = dist_data[si] - dist_data[si - 1]
                t_diff = time_data[si] - time_data[si - 1]
                speed_data.append(round((d_diff / t_diff * 3.6) if t_diff > 0 else 0.0, 2))
            transformed = {
                'time': time_data,
                'lat': [p[0] for p in s.get('latlng', {}).get('data', [])] if isinstance(s.get('latlng'), dict) else [],
                'lon': [p[1] for p in s.get('latlng', {}).get('data', [])] if isinstance(s.get('latlng'), dict) else [],
                'altitude': s.get('altitude', {}).get('data', []) if isinstance(s.get('altitude'), dict) else s.get('altitude', []),
                'heartrate': s.get('heartrate', {}).get('data', []) if isinstance(s.get('heartrate'), dict) else s.get('heartrate', []),
                'cadence': s.get('cadence', {}).get('data', []) if isinstance(s.get('cadence'), dict) else s.get('cadence', []),
                'power': s.get('watts', {}).get('data', []) if isinstance(s.get('watts'), dict) else s.get('watts', []),
                'distance': dist_data,
                'speed': speed_data,
            }
            d["streams"] = transformed
        return d

    @staticmethod
    def _fmt_time(seconds):
        if not seconds:
            return "0:00"
        h, r = divmod(int(seconds), 3600)
        m, s = divmod(r, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"


class Gear(Base):
    __tablename__ = "gear"
    id = Column(Integer, primary_key=True)
    name = Column(String(200))
    type = Column(String(50))
    brand = Column(String(100))
    model = Column(String(100))
    purchase_date = Column(Date)
    start_mileage_km = Column(Float, default=0)
    replacement_mileage_km = Column(Float, default=0)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,"name": self.name,"type": self.type,"brand": self.brand,"model": self.model,"purchase_date": str(self.purchase_date) if self.purchase_date else None,"start_mileage_km": self.start_mileage_km,"replacement_mileage_km": self.replacement_mileage_km,"notes": self.notes,"created_at": str(self.created_at) if self.created_at else None,"updated_at": str(self.updated_at) if self.updated_at else None,
        }


class HealthCheckin(Base):
    """Daily health check-in data (like Garmin Body Battery)."""
    __tablename__ = "health_checkins"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime, nullable=False, unique=True, index=True)

    # Heart rate
    resting_hr = Column(Float)
    max_hr = Column(Float)  # max recorded for the day
    avg_hr = Column(Float)
    min_hr = Column(Float)

    # HRV
    hrv_sdnn = Column(Float)  # Standard deviation of NN intervals
    hrv_rmssd = Column(Float)  # Root mean square of successive differences

    # Sleep
    sleep_hours = Column(Float)
    sleep_score = Column(Float)
    deep_sleep_hours = Column(Float)
    rem_sleep_hours = Column(Float)
    light_sleep_hours = Column(Float)
    awake_time_hours = Column(Float)

    # Recovery / Body Battery
    body_battery_high = Column(Float)
    body_battery_low = Column(Float)
    recovery_score = Column(Float)
    stress_level = Column(Float)

    # Activity
    steps = Column(Integer)
    calories_active = Column(Float)
    calories_total = Column(Float)

    # VO2max estimate
    vo2max = Column(Float)

    # Weight
    weight_kg = Column(Float)
    body_fat_pct = Column(Float)

    # Blood pressure (optional)
    systolic_bp = Column(Integer)
    diastolic_bp = Column(Integer)

    # Notes / tags
    notes = Column(Text)
    tags = Column(JSON)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "date": self.date.isoformat() if self.date else None,
            "resting_hr": self.resting_hr,
            "hrv_sdnn": self.hrv_sdnn,
            "hrv_rmssd": self.hrv_rmssd,
            "sleep_hours": round(self.sleep_hours, 1) if self.sleep_hours else None,
            "sleep_score": round(self.sleep_score) if self.sleep_score else None,
            "body_battery_high": round(self.body_battery_high) if self.body_battery_high else None,
            "body_battery_low": round(self.body_battery_low) if self.body_battery_low else None,
            "recovery_score": round(self.recovery_score) if self.recovery_score else None,
            "stress_level": round(self.stress_level) if self.stress_level else None,
            "steps": self.steps,
            "vo2max": round(self.vo2max, 1) if self.vo2max else None,
            "weight_kg": round(self.weight_kg, 1) if self.weight_kg else None,
        "body_fat_pct": round(self.body_fat_pct, 1) if self.body_fat_pct else None,
            "notes": self.notes,
        }


class DailyTrainingLoad(Base):
    """Daily training load summary — the Performance Management Chart data."""
    __tablename__ = "daily_training_load"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime, nullable=False, unique=True, index=True)

    # TSS for this day
    daily_tss = Column(Float, default=0)
    daily_kj = Column(Float, default=0)
    daily_distance_km = Column(Float, default=0)
    daily_time_s = Column(Float, default=0)

    # Performance Management Chart (TrainingPeaks-style)
    ctl = Column(Float, default=0)  # Chronic Training Load (fitness) — 42-day weighted avg
    atl = Column(Float, default=0)  # Acute Training Load (fatigue) — 7-day weighted avg
    tsb = Column(Float, default=0)  # Training Stress Balance (form) — CTL - ATL

    def to_dict(self):
        return {
            "date": self.date.isoformat() if self.date else None,
            "daily_tss": round(self.daily_tss or 0, 1),
            "daily_kj": round(self.daily_kj or 0),
            "daily_distance_km": round(self.daily_distance_km or 0, 2),
            "ctl": round(self.ctl or 0, 1),
            "atl": round(self.atl or 0, 1),
            "tsb": round(self.tsb or 0, 1),
        }


class WahooAccount(Base):
    """Wahoo OAuth account — stores tokens for auto-sync."""
    __tablename__ = "wahoo_accounts"

    id = Column(Integer, primary_key=True, index=True)
    wahoo_user_id = Column(String(100), unique=True)
    email = Column(String(255))
    first_name = Column(String(100))
    last_name = Column(String(100))
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=False)
    token_expires_at = Column(DateTime)
    scopes = Column(String(500))
    connected_at = Column(DateTime, default=datetime.utcnow)
    last_sync_at = Column(DateTime)
    sync_enabled = Column(Integer, default=1)  # boolean
    sync_interval_minutes = Column(Integer, default=15)
    is_active = Column(Integer, default=1)

    def to_dict(self):
        return {
            "id": self.id,
            "wahoo_user_id": self.wahoo_user_id,
            "email": self.email,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "connected_at": self.connected_at.isoformat() if self.connected_at else None,
            "last_sync_at": self.last_sync_at.isoformat() if self.last_sync_at else None,
            "sync_enabled": bool(self.sync_enabled),
            "sync_interval_minutes": self.sync_interval_minutes,
        }


class WahooWorkout(Base):
    """Tracks which Wahoo workouts have been imported to avoid duplicates."""
    __tablename__ = "wahoo_workouts"

    id = Column(Integer, primary_key=True, index=True)
    wahoo_workout_id = Column(Integer, nullable=False)
    wahoo_account_id = Column(Integer, ForeignKey("wahoo_accounts.id"))
    activity_id = Column(Integer, ForeignKey("activities.id"), nullable=True)
    name = Column(String(500))
    start_time = Column(DateTime)
    imported_at = Column(DateTime, default=datetime.utcnow)
    file_format = Column(String(10))


class PowerProfile(Base):
    """Best power outputs for various durations (5s, 1min, 5min, 20min, FTP, etc.)."""
    __tablename__ = "power_profiles"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime, nullable=False)
    duration_s = Column(Integer, nullable=False)  # Duration in seconds
    power_w = Column(Float, nullable=False)  # Best average power for this duration
    activity_id = Column(Integer, ForeignKey("activities.id"))
    activity = relationship("Activity")

    class Meta:
        unique_together = ("date", "duration_s")




class CoachNote(Base):
    """AI cycling coach daily notes."""
    __tablename__ = "coach_notes"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime, default=datetime.utcnow)
    note = Column(Text, nullable=False)
    prompt_data = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class AuthSession(Base):
    """User authentication sessions."""
    __tablename__ = "auth_sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    ip_address = Column(String(50))
    user_agent = Column(String(500))


def init_db():
    """Create all tables."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency for FastAPI to get DB sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
