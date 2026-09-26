from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.geo import GeoPoint


class SweepWaypoint(BaseModel):
    order: int
    position: GeoPoint


class SweepSession(BaseModel):
    id: str = Field(alias="_id")  # client-generated (Pi-assigned UUID)
    rover_id: str
    geofence_id: str
    status: Literal["in_progress", "interrupted", "completed"]
    pattern: list[SweepWaypoint]
    last_completed_waypoint_index: int
    started_at: datetime
    interrupted_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"populate_by_name": True}


class SweepSessionSyncBatch(BaseModel):
    sessions: list[SweepSession]
