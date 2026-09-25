"""Exclusion-zone intrusion depth checks. Supports the design spec's
Mission Flow rule: under one rover-length and easily reversible ->
auto-reverse, otherwise stop and wait for help. This module only
computes the geometric depth; the auto-reverse-vs-wait-for-help decision
belongs to the mission-flow state machine that calls it.
"""
from __future__ import annotations

from shapely.geometry import Point, Polygon

METERS_PER_DEGREE_LAT = 111_320.0


def exclusion_intrusion_depth_m(
    position: tuple[float, float], exclusion: Polygon
) -> float | None:
    """How many meters `position` (lon, lat) is inside `exclusion`, or
    None if it's outside. Flat-earth degrees-to-meters approximation --
    fine at the scale of a single geofenced field.
    """
    point = Point(position)
    if not exclusion.contains(point):
        return None
    degrees_to_boundary = exclusion.exterior.distance(point)
    return degrees_to_boundary * METERS_PER_DEGREE_LAT


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
