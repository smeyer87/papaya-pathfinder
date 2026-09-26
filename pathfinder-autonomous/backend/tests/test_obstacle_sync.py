from datetime import datetime, timezone

from app.models.geo import GeoPoint
from app.models.obstacle import Obstacle
from app.services import obstacles as obstacle_service

DETECTED_AT = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


def _obstacle(obstacle_id="obs-uuid-1", status="permanent-pending", review_status="pending"):
    return Obstacle(
        _id=obstacle_id,
        sweep_session_id="sess-uuid-1",
        position=GeoPoint(coordinates=(-85.0005, 38.0005)),
        position_uncertainty_m=1.5,
        type="barrel",
        classification_confidence=0.9,
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
    obstacle_service.sync_obstacles(db, [_obstacle()])

    confirmed = _obstacle(status="permanent-confirmed", review_status="confirmed")
    obstacle_service.sync_obstacles(db, [confirmed])

    stored = db.obstacles.find_one({"_id": "obs-uuid-1"})
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
