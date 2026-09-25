"""Converts raw sensor detections into Obstacle records, using the fused
position estimate for absolute placement. See design spec: Mission Flow
-- Execution loop (Detection, Bump contact).
"""
from __future__ import annotations

from datetime import datetime

from papaya_mission.classification import classify_permanence
from papaya_mission.geo_utils import project_position
from papaya_mission.obstacle import Obstacle
from papaya_mission.position_fusion import PositionEstimate


def obstacle_from_ultrasonic_camera_detection(
    rover_position: PositionEstimate,
    relative_bearing_deg: float,
    range_m: float,
    classified_type: str,
    classification_confidence: float,
    detected_at: datetime,
) -> Obstacle:
    """`relative_bearing_deg` is the ultrasonic/camera mast's angle
    relative to the rover's own heading (0 = straight ahead) -- the mast
    rotates independently of the chassis, so the detected object may not
    be dead ahead. Combined with the rover's current compass heading
    (from the fused position estimate) to get the absolute bearing the
    obstacle actually sits at before projecting outward by `range_m`.
    """
    absolute_bearing_deg = (rover_position.heading_deg + relative_bearing_deg) % 360.0

    obstacle_lat, obstacle_lon = project_position(
        rover_position.lat, rover_position.lon, absolute_bearing_deg, range_m
    )
    status = classify_permanence(classified_type, classification_confidence)

    return Obstacle(
        position=(obstacle_lon, obstacle_lat),
        position_uncertainty_m=rover_position.error_radius_m,
        type=classified_type,
        classification_confidence=classification_confidence,
        detection_method="ultrasonic+camera",
        status=status,
        first_detected_at=detected_at,
    )


def obstacle_from_bump_contact(
    rover_position: PositionEstimate,
    detected_at: datetime,
) -> Obstacle:
    """A reactive detection: something was hit that proactive sensors
    missed. The contact point is the rover's own current position -- no
    bearing/range to project, unlike a proactive ultrasonic+camera
    detection. No type classification is possible, so it's always
    flagged for human review (permanent-pending) rather than silently
    logged as temporary -- a bump contact is real, actionable
    information about a sensing gap, unlike a low-confidence camera
    reading that's more likely just noise.
    """
    return Obstacle(
        position=(rover_position.lon, rover_position.lat),
        position_uncertainty_m=rover_position.error_radius_m,
        type="unknown",
        classification_confidence=0.0,
        detection_method="contact-only",
        status="permanent-pending",
        first_detected_at=detected_at,
    )
