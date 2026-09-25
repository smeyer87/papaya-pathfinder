from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

CommandType = Literal[
    "start_sweep",
    "pause_sweep",
    "resume_sweep",
    "stop_sweep",
    "abort_home",
    "update_geofence",
]


class Command(BaseModel):
    id: str = Field(alias="_id")
    rover_id: str
    type: CommandType
    payload: dict[str, Any] = Field(default_factory=dict)
    status: Literal["pending", "delivered", "acked"] = "pending"
    created_at: datetime
    delivered_at: datetime | None = None
    acked_at: datetime | None = None

    model_config = {"populate_by_name": True}


class CommandCreate(BaseModel):
    rover_id: str
    type: CommandType
    payload: dict[str, Any] = Field(default_factory=dict)
