from datetime import datetime, timezone

from app.models.geo import GeoPoint
from app.models.sweep_session import SweepSession, SweepWaypoint
from app.services import sweep_sessions as sweep_session_service

STARTED_AT = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


def _session(session_id="sess-uuid-1", status="completed"):
    return SweepSession(
        _id=session_id,
        rover_id="rover-uuid-1",
        geofence_id="fence-uuid-1",
        status=status,
        pattern=[SweepWaypoint(order=0, position=GeoPoint(coordinates=(-85.0, 38.0)))],
        last_completed_waypoint_index=0,
        started_at=STARTED_AT,
        completed_at=STARTED_AT,
    )


def test_sync_sweep_sessions_inserts_new_records(db):
    count = sweep_session_service.sync_sweep_sessions(db, [_session()])

    assert count == 1
    stored = db.sweep_sessions.find_one({"_id": "sess-uuid-1"})
    assert stored is not None
    assert stored["status"] == "completed"


def test_sync_sweep_sessions_upserts_existing_record(db):
    sweep_session_service.sync_sweep_sessions(db, [_session()])

    updated = _session(status="interrupted")
    sweep_session_service.sync_sweep_sessions(db, [updated])

    stored = db.sweep_sessions.find_one({"_id": "sess-uuid-1"})
    assert stored["status"] == "interrupted"
    assert db.sweep_sessions.count_documents({}) == 1  # no duplicate


def test_sync_sweep_sessions_handles_empty_batch(db):
    count = sweep_session_service.sync_sweep_sessions(db, [])

    assert count == 0
