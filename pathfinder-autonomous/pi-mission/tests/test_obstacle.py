import dataclasses
from datetime import datetime, timezone

import pytest

from papaya_mission.obstacle import Obstacle

DETECTED_AT = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


def test_obstacle_is_constructible():
    obstacle = Obstacle(
        position=(-85.0005, 38.0005),
        position_uncertainty_m=2.0,
        type="barrel",
        classification_confidence=0.9,
        detection_method="ultrasonic+camera",
        status="permanent-pending",
        first_detected_at=DETECTED_AT,
    )

    assert obstacle.type == "barrel"
    assert obstacle.last_confirmed_at is None


def test_obstacle_is_immutable():
    obstacle = Obstacle(
        position=(-85.0005, 38.0005),
        position_uncertainty_m=2.0,
        type="barrel",
        classification_confidence=0.9,
        detection_method="ultrasonic+camera",
        status="permanent-pending",
        first_detected_at=DETECTED_AT,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        obstacle.type = "chair"
