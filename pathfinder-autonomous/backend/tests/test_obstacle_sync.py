from datetime import datetime, timezone

from app.models.geo import GeoPoint
from app.models.obstacle import Obstacle
from app.services import obstacles as obstacle_service

DETECTED_AT = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
REVIEWED_AT = datetime(2026, 9, 25, 9, 30, 0, tzinfo=timezone.utc)


def _obstacle(
    obstacle_id="obs-uuid-1",
    status="permanent-pending",
    review_status="pending",
    classification_confidence=0.9,
):
    return Obstacle(
        _id=obstacle_id,
        sweep_session_id="sess-uuid-1",
        position=GeoPoint(coordinates=(-85.0005, 38.0005)),
        position_uncertainty_m=1.5,
        type="barrel",
        classification_confidence=classification_confidence,
        detection_method="ultrasonic+camera",
        status=status,
        first_detected_at=DETECTED_AT,
        review_status=review_status,
    )


def test_sync_obstacles_inserts_new_records(db):
    count = obstacle_service.sync_obstacles(db, [_obstacle()])

    assert count == 1
    stored = db.obstacles.find_one({"_id": "obs-uuid-1"})
    assert stored is not None
    assert stored["type"] == "barrel"


def test_sync_obstacles_upserts_existing_record(db):
    """A re-sync must still update the fields the Pi owns.

    The scenario is deliberately one the Pi can actually produce: a first
    detection it is not yet sure about, then a re-detection on a later pass
    that promotes it to permanent-pending with higher confidence. (The
    previous version of this test had the second sync send
    status="permanent-confirmed"/review_status="confirmed", which no Pi can
    ever send -- papaya_mission.obstacle.ObstacleStatus has no
    "permanent-confirmed" member and the Pi's Obstacle has no review fields
    at all.)
    """
    obstacle_service.sync_obstacles(
        db, [_obstacle(status="temporary", classification_confidence=0.55)]
    )

    redetected = _obstacle(status="permanent-pending", classification_confidence=0.94)
    obstacle_service.sync_obstacles(db, [redetected])

    stored = db.obstacles.find_one({"_id": "obs-uuid-1"})
    assert stored["status"] == "permanent-pending"
    assert stored["classification_confidence"] == 0.94
    assert db.obstacles.count_documents({}) == 1


def test_resyncing_an_obstacle_does_not_revert_human_review_decision(db):
    """A routine Pi re-sync must not undo a human review.

    review_status/reviewed_by/reviewed_at are backend-owned; the Pi's own
    Obstacle type does not have them, so Pydantic fills them with defaults on
    every inbound payload. `status` is shared: the Pi owns the
    temporary -> permanent-pending promotion, but "permanent-confirmed" is a
    review outcome the Pi cannot express, so a re-sync must not downgrade it
    either.
    """
    # The Pi's initial detection.
    obstacle_service.sync_obstacles(db, [_obstacle(status="permanent-pending")])

    # A human reviews it in the backend/UI and confirms it.
    db.obstacles.update_one(
        {"_id": "obs-uuid-1"},
        {
            "$set": {
                "review_status": "confirmed",
                "reviewed_by": "someone",
                "reviewed_at": REVIEWED_AT,
                "status": "permanent-confirmed",
            }
        },
    )

    # Routine retry / backlog flush: the Pi resends exactly what it detected,
    # still reporting permanent-pending because it knows nothing of the review.
    obstacle_service.sync_obstacles(db, [_obstacle(status="permanent-pending")])

    stored = db.obstacles.find_one({"_id": "obs-uuid-1"})
    assert stored["review_status"] == "confirmed"
    assert stored["reviewed_by"] == "someone"
    assert stored["reviewed_at"] is not None
    assert stored["status"] == "permanent-confirmed"
    assert db.obstacles.count_documents({}) == 1


def test_list_pending_review_returns_only_permanent_pending_awaiting_review(db):
    obstacle_service.sync_obstacles(
        db,
        [
            _obstacle(obstacle_id="obs-1", status="permanent-pending", review_status="pending"),
            _obstacle(obstacle_id="obs-2", status="temporary", review_status="pending"),
            _obstacle(obstacle_id="obs-3", status="permanent-pending", review_status="confirmed"),
        ],
    )

    pending = obstacle_service.list_pending_review(db)

    assert [o.id for o in pending] == ["obs-1"]
    # BSON has no timezone, and pymongo hands datetimes back NAIVE unless the
    # client is built with tz_aware=True. A naive first_detected_at serialises
    # without a Z/offset, so a UI is free to read this Pi-supplied UTC instant
    # as local time. Assert the round trip keeps the zone.
    assert pending[0].first_detected_at.tzinfo is not None
    assert pending[0].first_detected_at == DETECTED_AT


def test_obstacle_position_supports_geospatial_query(db):
    obstacle_service.sync_obstacles(db, [_obstacle()])

    nearby = list(
        db.obstacles.find(
            {
                "position": {
                    "$near": {
                        "$geometry": {"type": "Point", "coordinates": [-85.0005, 38.0005]},
                        "$maxDistance": 10,
                    }
                }
            }
        )
    )

    assert len(nearby) == 1
