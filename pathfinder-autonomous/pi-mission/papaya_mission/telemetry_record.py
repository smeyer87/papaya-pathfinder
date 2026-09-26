"""Builds a telemetry record with the design spec's three-state metric
semantics. See design spec: Telemetry -- Expected metrics & missing-
value semantics.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def build_telemetry_record(
    record_id: str,
    rover_id: str,
    timestamp: datetime,
    local_tz_offset_minutes: int,
    sequence_number: int,
    readings: dict[str, Any],
    expected_metrics: set[str],
    sweep_session_id: str | None = None,
) -> dict[str, Any]:
    """`expected_metrics` is both floor and ceiling: every key in it
    appears in the output metrics map, either with its real value (if
    present in `readings`) or the "missing" sentinel (if not). Anything
    in `readings` outside `expected_metrics` is silently dropped --
    nothing is written for metrics outside the current sensor
    configuration, even if a stray reading happens to exist for it.
    """
    metrics = {key: readings.get(key, "missing") for key in expected_metrics}

    return {
        "id": record_id,
        "rover_id": rover_id,
        "timestamp": timestamp,
        "local_tz_offset_minutes": local_tz_offset_minutes,
        "sweep_session_id": sweep_session_id,
        "sequence_number": sequence_number,
        "metrics": metrics,
    }
