from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.geo import GeoPoint


class Obstacle(BaseModel):
    id: str = Field(alias="_id")  # client-generated (Pi-assigned UUID)
    sweep_session_id: str
    position: GeoPoint
    position_uncertainty_m: float
    type: str
    classification_confidence: float
    detection_method: Literal["ultrasonic+camera", "contact-only"]
    status: Literal["temporary", "permanent-pending", "permanent-confirmed"]
    first_detected_at: datetime
    last_confirmed_at: datetime | None = None
    review_status: Literal["pending", "confirmed", "rejected"] = "pending"
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None

    model_config = {"populate_by_name": True}


class ObstacleSyncBatch(BaseModel):
    obstacles: list[Obstacle]
