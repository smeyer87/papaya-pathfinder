"""Shared geometry helpers used across the position/coverage/obstacle
modules. Flat-earth degrees<->meters approximation throughout -- fine at
the scale of a single geofenced field (see each module's own docstring
for where this assumption originates).
"""
from __future__ import annotations

import math

METERS_PER_DEGREE_LAT = 111_320.0


def project_position(
    lat: float, lon: float, bearing_deg: float, distance_m: float
) -> tuple[float, float]:
    """Project a (lat, lon) point `distance_m` meters along `bearing_deg`
    (0 = north, clockwise positive). Returns (new_lat, new_lon). This is
    an ABSOLUTE compass bearing -- callers with a mast-relative bearing
    must combine it with the rover's own heading first (see
    obstacle_detection.py).
    """
    bearing_rad = math.radians(bearing_deg)
    new_lat = lat + (distance_m * math.cos(bearing_rad)) / METERS_PER_DEGREE_LAT
    new_lon = lon + (distance_m * math.sin(bearing_rad)) / (
        METERS_PER_DEGREE_LAT * math.cos(math.radians(lat))
    )
    return new_lat, new_lon


def flat_earth_distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Approximate distance in meters between two (lon, lat) points."""
    lon1, lat1 = a
    lon2, lat2 = b
    mean_lat_rad = math.radians((lat1 + lat2) / 2)
    dlat_m = (lat2 - lat1) * METERS_PER_DEGREE_LAT
    dlon_m = (lon2 - lon1) * METERS_PER_DEGREE_LAT * math.cos(mean_lat_rad)
    return math.hypot(dlat_m, dlon_m)
