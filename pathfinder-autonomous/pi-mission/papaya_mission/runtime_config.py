"""Runtime-wide named constants and .env-loaded settings for Mission
Runtime. See design notes: Decisions made so far, Global Constraints.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

# --- Loop timing -----------------------------------------------------------
# All overridable by editing this file. See design notes' "Scaling note"
# for the revisit trigger if TICK_HZ's 100ms budget ever gets tight.
TICK_HZ = 10
TICK_INTERVAL_S = 1.0 / TICK_HZ
COMMAND_POLL_INTERVAL_S = 1.0
TELEMETRY_SAMPLE_INTERVAL_S = 5.0

# --- GPS-loss safety thresholds ----------------------------------------------
# Whichever is hit first triggers stop_and_alert -- see
# papaya_mission.gps_loss_decision.decide_gps_loss_response.
GPS_LOSS_GRACE_PERIOD_S = 30.0
GPS_LOSS_MAX_ERROR_RADIUS_M = 5.0

# --- Coverage-pattern input ---------------------------------------------------
# Ultrasonic sensor's effective detection width in meters, sets row
# spacing (papaya_mission.row_spacing). PLACEHOLDER: the actual
# ultrasonic sensor part hasn't been selected yet (open item in the MP-1
# design spec's BOM) -- update this once it is.
SENSOR_DETECTION_WIDTH_M = 2.0


@dataclass(frozen=True)
class RuntimeSettings:
    rover_id: str
    backend_base_url: str
    local_db_path: str


def load_runtime_settings() -> RuntimeSettings:
    """Reads ROVER_ID/BACKEND_BASE_URL/LOCAL_DB_PATH from the environment
    (via .env, same convention as pathfinder-autonomous/backend/). Raises
    KeyError if any is missing -- fail loudly rather than silently
    defaulting to a placeholder that could mask a real misconfiguration.
    """
    return RuntimeSettings(
        rover_id=os.environ["ROVER_ID"],
        backend_base_url=os.environ["BACKEND_BASE_URL"],
        local_db_path=os.environ["LOCAL_DB_PATH"],
    )
