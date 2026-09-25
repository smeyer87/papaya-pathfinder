"""Boustrophedon (lawnmower) coverage-pattern generation over a geofence,
avoiding exclusion zones. Deliberately simple per the design spec's Route
Planning notes -- open fields, gentle slopes, no road-network routing.
"""
from __future__ import annotations

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

METERS_PER_DEGREE_LAT = 111_320.0


def generate_coverage_pattern(
    inclusive: Polygon,
    exclusions: list[Polygon],
    row_spacing_m: float,
) -> list[tuple[float, float]]:
    """Generate an ordered lawnmower waypoint path covering `inclusive`
    while avoiding `exclusions`. Returns [(lon, lat), ...].
    """
    if row_spacing_m <= 0:
        raise ValueError("row_spacing_m must be positive")

    allowed_area = inclusive
    if exclusions:
        allowed_area = inclusive.difference(unary_union(exclusions))

    if allowed_area.is_empty:
        return []

    minx, miny, maxx, maxy = inclusive.bounds
    row_spacing_deg = row_spacing_m / METERS_PER_DEGREE_LAT

    waypoints: list[tuple[float, float]] = []
    row_index = 0
    lat = miny + row_spacing_deg / 2  # start half a row in from the edge

    while lat <= maxy:
        row_line = LineString([(minx, lat), (maxx, lat)])
        intersection = allowed_area.intersection(row_line)

        segments = _as_line_segments(intersection)
        if row_index % 2 == 1:
            segments = [segment[::-1] for segment in reversed(segments)]

        for segment in segments:
            waypoints.extend(segment)

        lat += row_spacing_deg
        row_index += 1

    return waypoints


def _as_line_segments(geometry) -> list[list[tuple[float, float]]]:
    if geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [list(geometry.coords)]
    if geometry.geom_type == "MultiLineString":
        return [list(line.coords) for line in geometry.geoms]
    if geometry.geom_type == "Point":
        return []
    raise ValueError(
        f"unexpected row/allowed-area intersection type: {geometry.geom_type} "
        "-- likely a complex exclusion shape; extend this function to handle it"
    )
