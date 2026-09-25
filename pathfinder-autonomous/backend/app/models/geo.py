from typing import Literal

from pydantic import BaseModel, field_validator


def _check_position_ranges(
    position: tuple[float, float], where: str = ""
) -> tuple[float, float]:
    """Range-check a single [longitude, latitude] position.

    `where` is an optional suffix locating the position inside a larger geometry,
    e.g. " at ring 1, position 2".
    """
    lon, lat = position
    if not (-180.0 <= lon <= 180.0):
        raise ValueError(f"longitude {lon} out of range [-180, 180]{where}")
    if not (-90.0 <= lat <= 90.0):
        raise ValueError(f"latitude {lat} out of range [-90, 90]{where}")
    return position


class GeoPoint(BaseModel):
    """A GeoJSON Point. coordinates is [longitude, latitude] -- NOT lat/long."""

    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]

    @field_validator("coordinates")
    @classmethod
    def validate_ranges(cls, v: tuple[float, float]) -> tuple[float, float]:
        return _check_position_ranges(v)


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
        for ring_index, ring in enumerate(v):
            if len(ring) < 4:
                raise ValueError(
                    "each polygon ring needs at least 4 positions (closed ring)"
                )
            if ring[0] != ring[-1]:
                raise ValueError(
                    "polygon ring must be closed (first position == last position)"
                )
            for position_index, position in enumerate(ring):
                _check_position_ranges(
                    position,
                    f" at ring {ring_index}, position {position_index}",
                )
        return v
