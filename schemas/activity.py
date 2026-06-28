"""Activity schemas for Pydantic serialization."""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class ActivityRead(BaseModel):
    """Compact activity summary for list views (no streams)."""

    id: int
    name: str
    sport: str
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    distance_m: float = 0
    moving_time_s: int = 0
    avg_power_w: Optional[float] = None
    max_power_w: Optional[float] = None
    avg_heartrate: Optional[float] = None
    avg_cadence: Optional[float] = None
    elevation_gain_m: float = 0
    tss: Optional[float] = None
    intensity_factor: Optional[float] = None
    normalized_power_w: Optional[float] = None
    calories_kcal: Optional[float] = None

    class Config:
        orm_mode = True
