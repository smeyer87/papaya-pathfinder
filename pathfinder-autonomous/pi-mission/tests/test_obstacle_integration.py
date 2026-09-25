from datetime import datetime, timedelta, timezone

from papaya_mission.obstacle_detection import (
    obstacle_from_bump_contact,
    obstacle_from_ultrasonic_camera_detection,
)
from papaya_mission.position_fusion import PositionEstimate
from papaya_mission.resume_validation import reconcile_obstacles

FIRST_PASS = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
RESUME_PASS = FIRST_PASS + timedelta(hours=1)


def test_sweep_then_resume_pass_reconciles_correctly():
    rover_position = PositionEstimate(
        lat=38.0, lon=-85.0, heading_deg=0.0, error_radius_m=1.5, timestamp=0.0
    )

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
    assert bump_discovery.status == "permanent-pending"  # goes into the review queue separately
