"""The auto-reverse-vs-wait-for-help decision for an exclusion-zone
intrusion. See design spec: Mission Flow -- Exclusion-zone intrusion.
"""
from __future__ import annotations

from typing import Literal

ExclusionResponse = Literal["auto_reverse", "wait_for_help"]


def decide_exclusion_response(
    intrusion_depth_m: float, rover_length_m: float
) -> ExclusionResponse:
    """Under one rover-length deep -> auto-reverse. Otherwise (including
    exactly one rover-length) -> stop and wait for help.
    """
    if intrusion_depth_m < rover_length_m:
        return "auto_reverse"
    return "wait_for_help"
