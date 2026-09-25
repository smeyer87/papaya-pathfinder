# pathfinder-autonomous/pi-mission/tests/test_resume_validation.py
from datetime import datetime, timedelta, timezone

from papaya_mission.obstacle import Obstacle
from papaya_mission.resume_validation import reconcile_obstacles

FIRST_DETECTED = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
NOW = FIRST_DETECTED + timedelta(minutes=30)


def _obstacle(lon, lat, status, obstacle_type="barrel"):
    return Obstacle(
        position=(lon, lat),
        position_uncertainty_m=1.0,
        type=obstacle_type,
        classification_confidence=0.9,
        detection_method="ultrasonic+camera",
        status=status,
        first_detected_at=FIRST_DETECTED,
    )


def test_matched_obstacle_is_confirmed_with_updated_timestamp():
    known = _obstacle(-85.0, 38.0, "temporary")
    fresh = _obstacle(-85.0, 38.0, "temporary")

    result = reconcile_obstacles([known], [fresh], now=NOW)

    assert len(result.confirmed) == 1
    assert result.confirmed[0].last_confirmed_at == NOW
    assert result.confirmed[0].position == known.position
    assert result.cleared == []
    assert result.discrepancies == []


def test_missing_temporary_obstacle_is_cleared_not_flagged():
    known = _obstacle(-85.0, 38.0, "temporary")

    result = reconcile_obstacles([known], freshly_detected=[], now=NOW)

    assert result.cleared == [known]
    assert result.discrepancies == []
    assert result.confirmed == []


def test_missing_permanent_pending_obstacle_is_flagged_not_removed():
    known = _obstacle(-85.0, 38.0, "permanent-pending")

    result = reconcile_obstacles([known], freshly_detected=[], now=NOW)

    assert result.discrepancies == [known]
    assert result.cleared == []
    assert result.confirmed == []


def test_far_away_detection_does_not_count_as_a_match():
    known = _obstacle(-85.0, 38.0, "temporary")
    far_away = _obstacle(-84.0, 37.0, "temporary")  # well beyond match_radius_m

    result = reconcile_obstacles([known], [far_away], now=NOW, match_radius_m=3.0)

    assert result.cleared == [known]
    assert result.confirmed == []


def test_multiple_nearby_candidates_matches_the_first_one():
    """Verify that when multiple freshly_detected obstacles fall within
    match_radius_m of a known obstacle, the first one in the list is matched."""
    known = _obstacle(-85.0, 38.0, "temporary")
    # Both candidates are within 3m of known (roughly 0.000027 deg ≈ 3m)
    candidate_a = _obstacle(-85.000015, 38.0, "temporary")  # ~1.5m away
    candidate_b = _obstacle(-85.00003, 38.0, "temporary")   # ~3m away

    result = reconcile_obstacles([known], [candidate_a, candidate_b], now=NOW, match_radius_m=3.0)

    # Should confirm the known obstacle (with its original position)
    assert len(result.confirmed) == 1
    assert result.confirmed[0].position == known.position
    assert result.confirmed[0].last_confirmed_at == NOW
    assert result.cleared == []
    assert result.discrepancies == []
