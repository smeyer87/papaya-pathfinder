"""Exclusion-zone intrusion depth checks. Supports the design spec's
Mission Flow rule: under one rover-length and easily reversible ->
auto-reverse, otherwise stop and wait for help. This module only
computes the geometric depth; the auto-reverse-vs-wait-for-help decision
belongs to the mission-flow state machine that calls it.
"""
from __future__ import annotations

import math

from shapely.geometry import Point, Polygon
from shapely.ops import transform

from papaya_mission.geo_utils import METERS_PER_DEGREE_LAT


def exclusion_intrusion_depth_m(
    position: tuple[float, float], exclusion: Polygon
) -> float | None:
    """How many meters `position` (lon, lat) is inside `exclusion`, or
    None if it's outside -- i.e. the distance to the nearest point of the
    exclusion's boundary. Flat-earth degrees-to-meters approximation --
    fine at the scale of a single geofenced field.

    Both the point and the polygon are transformed into a local meters
    frame before measuring, because a degree of longitude spans only
    METERS_PER_DEGREE_LAT * cos(lat) meters; measuring in raw degrees
    overstates east-west depths (by 27% at latitude 38). `.boundary` is
    used rather than `.exterior` so that a hole's wall counts: for an
    exclusion shaped like a donut, the nearest edge may be an interior
    ring, not the outer one.
    """
    point = Point(position)
    if not exclusion.contains(point):
        return None

    lat = position[1]
    lon_scale_m = METERS_PER_DEGREE_LAT * math.cos(math.radians(lat))

    def to_local_meters(x, y, z=None):
        return (x * lon_scale_m, y * METERS_PER_DEGREE_LAT)

    scaled_point = transform(to_local_meters, point)
    scaled_exclusion = transform(to_local_meters, exclusion)
    return scaled_exclusion.boundary.distance(scaled_point)


def find_intruded_exclusion(
    position: tuple[float, float], exclusions: list[Polygon]
) -> tuple[Polygon, float] | None:
    """(exclusion_polygon, intrusion_depth_m) for the first exclusion zone
    `position` is inside, or None if outside all of them.
    """
    for exclusion in exclusions:
        depth = exclusion_intrusion_depth_m(position, exclusion)
        if depth is not None:
            return exclusion, depth
    return None
