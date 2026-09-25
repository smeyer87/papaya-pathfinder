from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SensorManifestEntry(BaseModel):
    sensor: str  # e.g. "gps", "imu", "ultrasonic", "ai_camera", "bump"
    installed: bool = True


class Rover(BaseModel):
    id: str = Field(alias="_id")
    name: str
    length_m: float | None = None
    width_m: float | None = None
    turn_style: Literal["spin_in_place", "graceful"] = "spin_in_place"
    min_turn_diameter_m: float | None = None  # only meaningful when turn_style="graceful"
    sensor_manifest: list[SensorManifestEntry] = Field(default_factory=list)
    supported_mission_packages: list[str] = Field(default_factory=list)
    status: Literal["active", "inactive"] = "inactive"
    notes: str = ""
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}


class RoverCreate(BaseModel):
    name: str
    length_m: float | None = None
    width_m: float | None = None
    turn_style: Literal["spin_in_place", "graceful"] = "spin_in_place"
    min_turn_diameter_m: float | None = None
    sensor_manifest: list[SensorManifestEntry] = Field(default_factory=list)
    supported_mission_packages: list[str] = Field(default_factory=list)
    notes: str = ""


class RoverUpdate(BaseModel):
    name: str | None = None
    length_m: float | None = None
    width_m: float | None = None
    turn_style: Literal["spin_in_place", "graceful"] | None = None
    min_turn_diameter_m: float | None = None
    sensor_manifest: list[SensorManifestEntry] | None = None
    supported_mission_packages: list[str] | None = None
    notes: str | None = None
