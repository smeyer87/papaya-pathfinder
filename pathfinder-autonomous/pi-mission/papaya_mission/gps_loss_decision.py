"""GPS-loss/degradation handling: continue briefly on dead reckoning,
then stop and alert. See design spec: Mission Flow -- GPS loss/
degradation, Architecture -- Positioning (error circle).
"""
from __future__ import annotations

from typing import Literal

GpsLossResponse = Literal["continue_dead_reckoning", "stop_and_alert"]


def decide_gps_loss_response(
    seconds_since_last_fix: float,
    current_error_radius_m: float,
    grace_period_s: float,
    max_error_radius_m: float,
) -> GpsLossResponse:
    """Continue on dead reckoning until EITHER the grace period elapses
    OR the error circle grows past a safe threshold, whichever comes
    first -- then stop and alert.
    """
    if seconds_since_last_fix > grace_period_s:
        return "stop_and_alert"
    if current_error_radius_m > max_error_radius_m:
        return "stop_and_alert"
    return "continue_dead_reckoning"
