"""Derives coverage-pattern row spacing from sensor detection width and
rover turning style. See design spec's Route Planning notes.
"""
from __future__ import annotations

from typing import Literal

TurnStyle = Literal["spin_in_place", "graceful"]


def derive_row_spacing_m(
    sensor_detection_width_m: float,
    turn_style: TurnStyle = "spin_in_place",
    min_turn_diameter_m: float | None = None,
) -> float:
    """Row spacing is set by the sensor's effective detection width, so
    adjacent rows' scan coverage meets with no gap -- this is a
    detection-coverage sweep, not a wheel-coverage lawnmower, and that
    part doesn't change with turn style.

    Turn style affects only a feasibility check. spin_in_place (Phase 1
    firmware's setSpin()) needs negligible turning radius, so it always
    fits -- though it can dig into soft terrain and costs more power
    than a gradual turn at speed. graceful needs `min_turn_diameter_m`
    of lateral room; if that's wider than the sensor's detection width,
    the row-to-row turn won't fit within the coverage spacing alone.
    This surfaces as an error rather than silently widening the spacing
    for you -- accepting coverage overlap to make room is a real
    tradeoff the caller should decide on, not something to default past.
    """
    if sensor_detection_width_m <= 0:
        raise ValueError(
            f"sensor_detection_width_m must be > 0, got {sensor_detection_width_m}"
        )
    if (
        turn_style == "graceful"
        and min_turn_diameter_m is not None
        and min_turn_diameter_m > sensor_detection_width_m
    ):
        raise ValueError(
            f"a graceful turn needs {min_turn_diameter_m}m of room, wider than the "
            f"{sensor_detection_width_m}m sensor detection width -- either widen row "
            "spacing (accepting coverage overlap) or use spin_in_place turns instead"
        )
    return sensor_detection_width_m
