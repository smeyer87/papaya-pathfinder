"""Boustrophedon (lawnmower) coverage-pattern generation over a geofence,
avoiding exclusion zones. Deliberately simple per the design spec's Route
Planning notes -- open fields, gentle slopes, no road-network routing.
"""
from __future__ import annotations

import math

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

METERS_PER_DEGREE_LAT = 111_320.0


def generate_coverage_pattern(
    inclusive: Polygon,
    exclusions: list[Polygon],
    row_spacing_m: float,
) -> list[list[tuple[float, float]]]:
    """Generate an ordered lawnmower coverage pattern over `inclusive`
    while avoiding `exclusions`.

    Returns a list of *legs*: [[(lon, lat), ...], ...]. Each leg is one
    contiguous, directly drivable polyline -- a straight line between any
    two consecutive points *within* a leg stays out of every exclusion
    zone. A row that no exclusion touches contributes one leg; a row an
    exclusion splits in two contributes two legs.

    Consumers must treat each leg as independently drivable and are
    responsible for routing the rover from the end of one leg to the start
    of the next -- this library does no road-network routing (per the
    design spec's Route Planning scope). Do NOT concatenate the legs back
    into a single flat path: the joins between legs are exactly the gaps
    that exist because an exclusion zone sits between them, so driving
    them straight would cut through the exclusion.
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

    # Distribute the rows evenly across the full height rather than stepping
    # by a fixed spacing from the south edge: a leftover strip shorter than one
    # row spacing would otherwise be dropped with no warning (a 40m field at
    # 30m spacing got a single row at 15m, leaving 62% uncovered). Computing
    # each row's latitude from its index also avoids float drift from
    # repeatedly accumulating `lat += row_spacing_deg`.
    height_deg = maxy - miny
    n_rows = max(1, math.ceil(height_deg / row_spacing_deg))
    row_lats = [miny + (i + 0.5) * height_deg / n_rows for i in range(n_rows)]

    legs: list[list[tuple[float, float]]] = []

    for row_index, lat in enumerate(row_lats):
        row_line = LineString([(minx, lat), (maxx, lat)])
        intersection = allowed_area.intersection(row_line)

        segments = _as_line_segments(intersection)
        if row_index % 2 == 1:
            segments = [segment[::-1] for segment in reversed(segments)]

        legs.extend(segments)

    return legs


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
