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


def test_multiple_nearby_candidates_matches_the_nearest_one():
    """When several freshly_detected obstacles fall within match_radius_m of
    the same known obstacle, matching is nearest-first: the closest candidate
    claims the match and the rest are left over as new detections (list order
    is deliberately farthest-first here so "first" and "nearest" differ)."""
    known = _obstacle(-85.0, 38.0, "temporary")
    # Both candidates are within 3m of known (roughly 0.000027 deg ~ 3m)
    far_candidate = _obstacle(-85.00003, 38.0, "temporary")   # ~2.6m away
    near_candidate = _obstacle(-85.000015, 38.0, "temporary")  # ~1.3m away

    result = reconcile_obstacles(
        [known], [far_candidate, near_candidate], now=NOW, match_radius_m=3.0
    )

    # Should confirm the known obstacle (with its original position)
    assert len(result.confirmed) == 1
    assert result.confirmed[0].position == known.position
    assert result.confirmed[0].last_confirmed_at == NOW
    assert result.cleared == []
    assert result.discrepancies == []
    # The nearest candidate was consumed by the match; the other is new.
    assert result.new_detections == [far_candidate]


def test_one_fresh_detection_cannot_confirm_two_known_obstacles():
    """Matching is one-to-one. Two known posts 2m apart with only one of them
    re-detected must surface the missing one, not report both confirmed."""
    detected_again = _obstacle(-85.0, 38.0, "permanent-pending")
    # ~2m north of the other -- inside match_radius_m of the single fresh hit.
    still_missing = _obstacle(-85.0, 38.0000180, "permanent-pending")
    fresh = _obstacle(-85.0, 38.0, "permanent-pending")

    result = reconcile_obstacles(
        [detected_again, still_missing], [fresh], now=NOW, match_radius_m=3.0
    )

    assert len(result.confirmed) == 1
    assert result.confirmed[0].position == detected_again.position
    assert result.discrepancies == [still_missing]
    assert result.cleared == []
    assert result.new_detections == []


def test_nearest_first_matching_is_order_independent():
    """The greedy pass sorts by distance, so the known obstacle listed second
    still wins the fresh detection it is closest to."""
    far_known = _obstacle(-85.0, 38.0000180, "permanent-pending")  # ~2m away
    near_known = _obstacle(-85.0, 38.0, "permanent-pending")
    fresh = _obstacle(-85.0, 38.0, "permanent-pending")

    result = reconcile_obstacles([far_known, near_known], [fresh], now=NOW, match_radius_m=3.0)

    assert len(result.confirmed) == 1
    assert result.confirmed[0].position == near_known.position
    assert result.discrepancies == [far_known]


def test_unmatched_fresh_detection_is_reported_as_a_new_detection():
    known = _obstacle(-85.0, 38.0, "temporary")
    brand_new = _obstacle(-84.0, 37.0, "permanent-pending")  # well beyond match_radius_m

    result = reconcile_obstacles([known], [brand_new], now=NOW, match_radius_m=3.0)

    assert result.new_detections == [brand_new]
    assert result.confirmed == []
    assert result.cleared == [known]


def test_matched_fresh_detection_is_not_reported_as_new():
    known = _obstacle(-85.0, 38.0, "temporary")
    fresh = _obstacle(-85.0, 38.0, "temporary")

    result = reconcile_obstacles([known], [fresh], now=NOW)

    assert result.new_detections == []
