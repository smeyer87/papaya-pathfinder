import math
from datetime import datetime, timezone

from papaya_mission.obstacle_detection import (
    obstacle_from_bump_contact,
    obstacle_from_ultrasonic_camera_detection,
)
from papaya_mission.position_fusion import PositionEstimate

DETECTED_AT = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)

# Rover facing east (heading 90) -- deliberately non-north so these tests
# actually exercise the relative-bearing + heading combination instead of
# accidentally passing with heading silently treated as zero.
ROVER_POSITION = PositionEstimate(
    lat=38.0, lon=-85.0, heading_deg=90.0, error_radius_m=1.5, timestamp=10.0
)


def test_relative_bearing_zero_combines_with_rover_heading():
    # Straight ahead (relative bearing 0) while facing east should place
    # the obstacle east of the rover, not north.
    obstacle = obstacle_from_ultrasonic_camera_detection(
        rover_position=ROVER_POSITION,
        relative_bearing_deg=0.0,
        range_m=10.0,
        classified_type="barrel",
        classification_confidence=0.9,
        detected_at=DETECTED_AT,
    )

    obstacle_lon, obstacle_lat = obstacle.position
    assert obstacle_lon > ROVER_POSITION.lon
    assert math.isclose(obstacle_lat, ROVER_POSITION.lat, abs_tol=1e-6)


def test_relative_bearing_offsets_from_rover_heading():
    # Mast turned 270 degrees relative to the chassis while facing east
    # (heading 90) works out to absolute bearing 0 (north): 90+270=360=0.
    obstacle = obstacle_from_ultrasonic_camera_detection(
        rover_position=ROVER_POSITION,
        relative_bearing_deg=270.0,
        range_m=10.0,
        classified_type="barrel",
        classification_confidence=0.9,
        detected_at=DETECTED_AT,
    )

    obstacle_lon, obstacle_lat = obstacle.position
    assert obstacle_lat > ROVER_POSITION.lat
    assert math.isclose(obstacle_lon, ROVER_POSITION.lon, abs_tol=1e-6)


def test_obstacle_type_status_and_uncertainty_still_set_correctly():
    obstacle = obstacle_from_ultrasonic_camera_detection(
        rover_position=ROVER_POSITION,
        relative_bearing_deg=0.0,
        range_m=10.0,
        classified_type="barrel",
        classification_confidence=0.9,
        detected_at=DETECTED_AT,
    )

    assert obstacle.type == "barrel"
    assert obstacle.status == "permanent-pending"
    assert obstacle.detection_method == "ultrasonic+camera"
    assert obstacle.position_uncertainty_m == ROVER_POSITION.error_radius_m
    assert obstacle.first_detected_at == DETECTED_AT


def test_ultrasonic_camera_detection_low_confidence_stays_temporary():
    obstacle = obstacle_from_ultrasonic_camera_detection(
        rover_position=ROVER_POSITION,
        relative_bearing_deg=0.0,
        range_m=10.0,
        classified_type="barrel",
        classification_confidence=0.1,
        detected_at=DETECTED_AT,
    )

    assert obstacle.status == "temporary"


def test_bump_contact_is_always_permanent_pending_and_unknown_type():
    obstacle = obstacle_from_bump_contact(rover_position=ROVER_POSITION, detected_at=DETECTED_AT)

    assert obstacle.type == "unknown"
    assert obstacle.status == "permanent-pending"
    assert obstacle.detection_method == "contact-only"
    assert obstacle.position == (ROVER_POSITION.lon, ROVER_POSITION.lat)
    assert obstacle.first_detected_at == DETECTED_AT
