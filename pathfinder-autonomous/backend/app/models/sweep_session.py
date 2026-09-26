from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.geo import GeoPoint


class SweepWaypoint(BaseModel):
    order: int
    position: GeoPoint
    # Which contiguous leg of the sweep row this waypoint belongs to --
    # exclusion-zone gaps split one row into several legs. Set on the Pi
    # and carried through its local store and sync payload; without this
    # field Pydantic's default extra="ignore" silently dropped it here.
    # Defaults to 0 (one unsplit leg) for sessions synced before it
    # existed.
    leg_index: int = 0


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
