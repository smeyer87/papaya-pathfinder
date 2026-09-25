from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.geo import GeoPolygon


class Geofence(BaseModel):
    id: str = Field(alias="_id")
    type: Literal["inclusive", "exclusive"]
    boundary: GeoPolygon
    name: str
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}


class GeofenceCreate(BaseModel):
    type: Literal["inclusive", "exclusive"]
    boundary: GeoPolygon
    name: str
