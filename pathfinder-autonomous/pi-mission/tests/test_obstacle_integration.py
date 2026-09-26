import math
from datetime import datetime, timedelta, timezone

from papaya_mission.obstacle_detection import (
    obstacle_from_bump_contact,
    obstacle_from_ultrasonic_camera_detection,
)
from papaya_mission.position_fusion import GpsFix, ImuReading, PositionFusion
from papaya_mission.resume_validation import reconcile_obstacles

FIRST_PASS = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
RESUME_PASS = FIRST_PASS + timedelta(hours=1)

START_LAT, START_LON = 38.0, -85.0
FIX_ACCURACY_M = 1.5
DRIFT_RATE_M_PER_S = 0.5


def _rover_facing_east():
    """A real PositionFusion turned off north, not a hand-built estimate.

    Routing through the fusion object is the point of this test: with a
    hand-built `heading_deg=0.0` estimate, `(0 + relative_bearing) % 360`
    equals the relative bearing, so the obstacle placement assertions
    would still hold even if obstacle_detection.py stopped combining the
    rover heading at all. Heading 90 (east) makes that seam load-bearing.

    Zero forward acceleration keeps the rover stationary while it turns,
    so positions stay exactly at the seed fix and the assertions below
    are about bearing alone.
    """
    fusion = PositionFusion(
        GpsFix(lat=START_LAT, lon=START_LON, accuracy_m=FIX_ACCURACY_M, timestamp=0.0),
        drift_rate_m_per_s=DRIFT_RATE_M_PER_S,
    )
    fusion.on_imu_reading(
        ImuReading(heading_deg=90.0, forward_acceleration_mps2=0.0, timestamp=1.0)
    )
    return fusion


def test_sweep_then_resume_pass_reconciles_correctly():
    fusion = _rover_facing_east()
    rover_position = fusion.current_estimate
    assert rover_position.heading_deg == 90.0

    barrel = obstacle_from_ultrasonic_camera_detection(
        rover_position,
        relative_bearing_deg=0.0,
        range_m=5.0,
        classified_type="barrel",
        classification_confidence=0.9,
        detected_at=FIRST_PASS,
    )
    chair = obstacle_from_ultrasonic_camera_detection(
        rover_position,
        relative_bearing_deg=180.0,
        range_m=5.0,
        classified_type="chair",
        classification_confidence=0.9,
        detected_at=FIRST_PASS + timedelta(seconds=1),
    )
    known_obstacles = [barrel, chair]
    assert barrel.status == "permanent-pending"
    assert chair.status == "temporary"

    # The IMU-tracked heading must actually reach obstacle placement: a
    # straight-ahead detection while facing east belongs east of the
    # rover, and one dead astern belongs west -- neither is north.
    barrel_lon, barrel_lat = barrel.position
    assert barrel_lon > rover_position.lon
    assert math.isclose(barrel_lat, rover_position.lat, abs_tol=1e-6)

    chair_lon, chair_lat = chair.position
    assert chair_lon < rover_position.lon
    assert math.isclose(chair_lat, rover_position.lat, abs_tol=1e-6)

    # Uncertainty is the fusion object's grown error radius, not the raw
    # seed fix's accuracy -- more evidence the estimate is the real one.
    assert barrel.position_uncertainty_m == FIX_ACCURACY_M + DRIFT_RATE_M_PER_S * 1.0

    # Resume pass: the barrel is still there, the chair has been moved
    # (no longer detected), and a bump reveals something proactive
    # sensors missed entirely.
    fresh_barrel = obstacle_from_ultrasonic_camera_detection(
        rover_position,
        relative_bearing_deg=0.0,
        range_m=5.0,
        classified_type="barrel",
        classification_confidence=0.9,
        detected_at=RESUME_PASS,
    )
    bump_discovery = obstacle_from_bump_contact(
        rover_position, detected_at=RESUME_PASS + timedelta(seconds=1)
    )

    result = reconcile_obstacles(known_obstacles, [fresh_barrel], now=RESUME_PASS)

    assert len(result.confirmed) == 1
    assert result.confirmed[0].type == "barrel"
    assert result.cleared == [chair]
    assert result.discrepancies == []
    assert result.new_detections == []
    # A bump contact is placed at the rover itself, so it tracks the fused
    # position rather than any bearing.
    assert bump_discovery.position == rover_position.as_lon_lat()
    assert bump_discovery.status == "permanent-pending"  # goes into the review queue separately
