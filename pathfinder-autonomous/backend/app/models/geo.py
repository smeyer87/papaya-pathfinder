from typing import Literal

from pydantic import BaseModel, field_validator


class GeoPoint(BaseModel):
    """A GeoJSON Point. coordinates is [longitude, latitude] -- NOT lat/long."""

    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]

    @field_validator("coordinates")
    @classmethod
    def validate_ranges(cls, v: tuple[float, float]) -> tuple[float, float]:
        lon, lat = v
        if not (-180.0 <= lon <= 180.0):
            raise ValueError(f"longitude {lon} out of range [-180, 180]")
        if not (-90.0 <= lat <= 90.0):
            raise ValueError(f"latitude {lat} out of range [-90, 90]")
        return v


class GeoPolygon(BaseModel):
    """A GeoJSON Polygon. Each ring's positions are [longitude, latitude]."""

    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[tuple[float, float]]]

    @field_validator("coordinates")
    @classmethod
    def validate_rings(
        cls, v: list[list[tuple[float, float]]]
    ) -> list[list[tuple[float, float]]]:
        if not v:
            raise ValueError("polygon must have at least one ring")
        for ring in v:
            if len(ring) < 4:
                raise ValueError(
                    "each polygon ring needs at least 4 positions (closed ring)"
                )
            if ring[0] != ring[-1]:
                raise ValueError(
                    "polygon ring must be closed (first position == last position)"
                )
        return v
