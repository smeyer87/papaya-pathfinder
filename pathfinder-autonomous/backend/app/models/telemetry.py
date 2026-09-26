from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TelemetryRecord(BaseModel):
    id: str = Field(alias="_id")  # client-generated (Pi-assigned UUID) -- guards retries
    rover_id: str
    timestamp: datetime
    local_tz_offset_minutes: int
    sweep_session_id: str | None = None
    sequence_number: int
    metrics: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class TelemetrySyncBatch(BaseModel):
    records: list[TelemetryRecord]
