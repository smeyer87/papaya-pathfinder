import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from papaya_mission import local_store

DETECTED_AT = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def conn():
    connection = local_store.connect(":memory:")
    yield connection
    connection.close()


def _obstacle(obstacle_id="obs-1", status="permanent-pending"):
    return {
        "id": obstacle_id,
        "sweep_session_id": "sess-1",
        "position": (-85.0005, 38.0005),
        "position_uncertainty_m": 1.5,
        "type": "barrel",
        "classification_confidence": 0.9,
        "detection_method": "ultrasonic+camera",
        "status": status,
        "first_detected_at": DETECTED_AT,
        "last_confirmed_at": None,
    }


def _sweep_session(session_id="sess-1", status="in_progress"):
    return {
        "id": session_id,
        "rover_id": "rover-1",
        "geofence_id": "fence-1",
        "status": status,
        "pattern": [{"order": 0, "position": {"type": "Point", "coordinates": [-85.0, 38.0]}}],
        "last_completed_waypoint_index": -1,
        "started_at": DETECTED_AT,
        "interrupted_at": None,
        "completed_at": None,
    }


def _telemetry_record(record_id="tel-1", sequence_number=1):
    return {
        "id": record_id,
        "rover_id": "rover-1",
        "timestamp": DETECTED_AT,
        "local_tz_offset_minutes": -300,
        "sweep_session_id": "sess-1",
        "sequence_number": sequence_number,
        "metrics": {"battery_voltage": 11.8},
    }


# --- Obstacles ---------------------------------------------------------

def test_save_and_list_unsynced_obstacle(conn):
    local_store.save_obstacle(conn, _obstacle())

    unsynced = local_store.list_unsynced_obstacles(conn)

    assert len(unsynced) == 1
    assert unsynced[0]["id"] == "obs-1"
    assert unsynced[0]["position"] == (-85.0005, 38.0005)
    assert unsynced[0]["first_detected_at"] == DETECTED_AT


def test_mark_obstacles_synced_excludes_them_from_unsynced_list(conn):
    local_store.save_obstacle(conn, _obstacle())

    local_store.mark_obstacles_synced(
        conn, ["obs-1"], datetime(2026, 9, 24, 13, 0, 0, tzinfo=timezone.utc)
    )

    assert local_store.list_unsynced_obstacles(conn) == []


def test_updating_a_synced_obstacle_marks_it_unsynced_again(conn):
    local_store.save_obstacle(conn, _obstacle())
    local_store.mark_obstacles_synced(
        conn, ["obs-1"], datetime(2026, 9, 24, 13, 0, 0, tzinfo=timezone.utc)
    )
    assert local_store.list_unsynced_obstacles(conn) == []

    local_store.save_obstacle(conn, _obstacle(status="permanent-confirmed"))

    unsynced = local_store.list_unsynced_obstacles(conn)
    assert len(unsynced) == 1
    assert unsynced[0]["status"] == "permanent-confirmed"


def test_saving_an_obstacle_again_refreshes_position_and_confidence(conn):
    local_store.save_obstacle(conn, _obstacle())

    refined = _obstacle()
    refined["position"] = (-85.0006, 38.0006)
    refined["classification_confidence"] = 0.95
    local_store.save_obstacle(conn, refined)

    unsynced = local_store.list_unsynced_obstacles(conn)
    assert len(unsynced) == 1
    assert unsynced[0]["position"] == (-85.0006, 38.0006)
    assert unsynced[0]["classification_confidence"] == 0.95


# --- Sweep sessions ------------------------------------------------------

def test_save_and_list_unsynced_sweep_session(conn):
    local_store.save_sweep_session(conn, _sweep_session())

    unsynced = local_store.list_unsynced_sweep_sessions(conn)

    assert len(unsynced) == 1
    assert unsynced[0]["id"] == "sess-1"
    assert unsynced[0]["pattern"][0]["order"] == 0


def test_updating_a_synced_sweep_session_marks_it_unsynced_again(conn):
    local_store.save_sweep_session(conn, _sweep_session())
    local_store.mark_sweep_sessions_synced(
        conn, ["sess-1"], datetime(2026, 9, 24, 13, 0, 0, tzinfo=timezone.utc)
    )
    assert local_store.list_unsynced_sweep_sessions(conn) == []

    local_store.save_sweep_session(conn, _sweep_session(status="completed"))

    unsynced = local_store.list_unsynced_sweep_sessions(conn)
    assert len(unsynced) == 1
    assert unsynced[0]["status"] == "completed"


# --- Telemetry -------------------------------------------------------------

def test_save_and_list_unsynced_telemetry(conn):
    local_store.save_telemetry_record(conn, _telemetry_record())

    unsynced = local_store.list_unsynced_telemetry(conn)

    assert len(unsynced) == 1
    assert unsynced[0]["metrics"]["battery_voltage"] == 11.8


def test_mark_telemetry_synced_excludes_it_from_unsynced_list(conn):
    local_store.save_telemetry_record(conn, _telemetry_record())

    local_store.mark_telemetry_synced(
        conn, ["tel-1"], datetime(2026, 9, 24, 13, 0, 0, tzinfo=timezone.utc)
    )

    assert local_store.list_unsynced_telemetry(conn) == []


def test_saving_the_same_telemetry_record_twice_is_a_no_op(conn):
    local_store.save_telemetry_record(conn, _telemetry_record())
    local_store.save_telemetry_record(conn, _telemetry_record())  # e.g. a retry

    unsynced = local_store.list_unsynced_telemetry(conn)
    assert len(unsynced) == 1


def test_telemetry_writes_are_not_durable_until_explicit_commit():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test.db")
        writer_conn = local_store.connect(db_path)
        try:
            local_store.save_telemetry_record(writer_conn, _telemetry_record())

            # A second connection to the same file shouldn't see the
            # uncommitted write yet -- proves save_telemetry_record
            # really doesn't auto-commit.
            reader_conn = local_store.connect(db_path)
            try:
                assert local_store.list_unsynced_telemetry(reader_conn) == []
            finally:
                reader_conn.close()

            local_store.commit(writer_conn)

            reader_conn = local_store.connect(db_path)
            try:
                assert len(local_store.list_unsynced_telemetry(reader_conn)) == 1
            finally:
                reader_conn.close()
        finally:
            writer_conn.close()


# --- Commit-interval helper (configurable, not hardcoded) ------------------

def test_should_commit_telemetry_true_when_nothing_committed_yet():
    assert local_store.should_commit_telemetry(last_commit_at=None, now=DETECTED_AT) is True


def test_should_commit_telemetry_false_before_interval_elapses():
    result = local_store.should_commit_telemetry(
        last_commit_at=DETECTED_AT, now=DETECTED_AT, interval_s=60.0
    )

    assert result is False


def test_should_commit_telemetry_true_once_interval_elapses():
    now = DETECTED_AT + timedelta(seconds=61)

    result = local_store.should_commit_telemetry(
        last_commit_at=DETECTED_AT, now=now, interval_s=60.0
    )

    assert result is True


def test_should_commit_telemetry_uses_the_configurable_default_interval():
    just_before_default = DETECTED_AT + timedelta(
        seconds=local_store.DEFAULT_TELEMETRY_COMMIT_INTERVAL_S - 1
    )

    result = local_store.should_commit_telemetry(DETECTED_AT, just_before_default)

    assert result is False
