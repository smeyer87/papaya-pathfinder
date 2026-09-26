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


def test_sync_sweep_sessions_preserves_waypoint_leg_index(db):
    """A Waypoint's leg_index (which legs an exclusion-zone gap splits a
    sweep row into) survives the Pi's local SQLite store and its wire
    payload, but used to be dropped here because SweepWaypoint had no
    such field and Pydantic v2 ignores extras by default.
    """
    session = SweepSession(
        _id="sess-uuid-legs",
        rover_id="rover-uuid-1",
        geofence_id="fence-uuid-1",
        status="completed",
        pattern=[
            SweepWaypoint(order=0, position=GeoPoint(coordinates=(-85.0, 38.0)), leg_index=0),
            SweepWaypoint(order=1, position=GeoPoint(coordinates=(-85.001, 38.001)), leg_index=2),
        ],
        last_completed_waypoint_index=1,
        started_at=STARTED_AT,
        completed_at=STARTED_AT,
    )

    sweep_session_service.sync_sweep_sessions(db, [session])

    stored = db.sweep_sessions.find_one({"_id": "sess-uuid-legs"})
    assert [wp["leg_index"] for wp in stored["pattern"]] == [0, 2]
    # And it round-trips back through the model, not just into Mongo.
    assert [wp.leg_index for wp in SweepSession(**stored).pattern] == [0, 2]


def test_sweep_waypoint_leg_index_defaults_to_zero_for_older_records(db):
    """Sessions synced before leg_index existed have no such key; they
    must still parse, defaulting to leg 0 (a single unsplit leg).
    """
    waypoint = SweepWaypoint(order=0, position=GeoPoint(coordinates=(-85.0, 38.0)))

    assert waypoint.leg_index == 0
