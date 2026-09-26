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

# --- Telemetry expected-metric keys -------------------------------------------
# Telemetry metric keys MP-1 always expects, independent of the sensor
# manifest (which lists physical sensors like "gps"/"imu"/"bump", not
# derived/computed telemetry fields like these). Unioned with the
# manifest in MissionRuntime.startup() to build the full expected set.
#
# build_telemetry_record treats the expected set as both floor AND
# ceiling: anything absent is stored as "missing", anything present in
# the readings but NOT expected is silently dropped. So a key that isn't
# listed here (and isn't a manifest sensor) never reaches the backend.
#
# Per-servo keys are the one thing that cannot live in this static set:
# they are named `servo_{id}_deg` from whatever ids the ESP32 actually
# reports in DriveStatus.servo_positions_deg on a given tick, which is
# not knowable ahead of time (and will change once the steering-servo
# naming convention is settled). _sample_telemetry_if_due therefore
# extends this set on the fly with that tick's real servo keys before
# calling build_telemetry_record. Do not try to pre-enumerate servo
# names here.
MP1_EXPECTED_METRICS = {
    "position",
    "position_uncertainty_m",
    "heading_deg",
    "error_radius_m",
    "nav_mode",
    "waypoint_index",
    "throttle_position",
    "mission_alert",
}


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
