# pathfinder-autonomous/pi-mission/tests/test_runtime_resume.py
import logging
from datetime import datetime, timezone

import httpx
import pytest

from papaya_mission.esp32_link import FakeEsp32Link
from papaya_mission.position_fusion import ImuReading
from papaya_mission.runtime import MissionRuntime
from papaya_mission.sensor_hub import SimulatedSensorHub
from papaya_mission.sweep_session import SweepSessionStatus
from papaya_mission import local_store

INITIAL_IMU = ImuReading(heading_deg=0.0, forward_acceleration_mps2=0.0, timestamp=0.0)
FIELD_RING = [[-85.10, 38.00], [-85.10, 38.10], [-84.90, 38.10], [-84.90, 38.00], [-85.10, 38.00]]


def _handler(rover, geofences):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rovers/rover-1":
            return httpx.Response(200, json=rover)
        if request.url.path == "/geofences":
            return httpx.Response(200, json=geofences)
        if request.url.path.startswith("/geofences/"):
            fid = request.url.path.rsplit("/", 1)[-1]
            match = next(g for g in geofences if g["_id"] == fid)
            return httpx.Response(200, json=match)
        if request.url.path.startswith("/commands/poll/"):
            # See test_digital_twin_scenarios.py's _handler for the full
            # rationale -- same fix, same reason.
            return httpx.Response(200, json=[])
        raise AssertionError(request.url.path)

    return handler


def _make_runtime(tmp_path, rover, geofences) -> tuple[MissionRuntime, str]:
    db_path = str(tmp_path / "test.db")
    client = httpx.Client(transport=httpx.MockTransport(_handler(rover, geofences)))
    runtime = MissionRuntime(
        rover_id="rover-1",
        backend_base_url="http://backend.local",
        local_db_path=db_path,
        sensor_hub=SimulatedSensorHub(INITIAL_IMU),
        esp32_link=FakeEsp32Link(),
        http_client=client,
    )
    return runtime, db_path


def test_startup_with_no_prior_session_stays_idle(tmp_path):
    rover = {"_id": "rover-1", "name": "George"}
    runtime, _ = _make_runtime(tmp_path, rover, geofences=[])

    runtime.startup()

    assert runtime.sweep_session is None


def test_startup_auto_resumes_interrupted_session(tmp_path):
    rover = {"_id": "rover-1", "name": "George"}
    inclusive = {"_id": "fence-1", "type": "inclusive", "boundary": {"type": "Polygon", "coordinates": [FIELD_RING]}}
    runtime, db_path = _make_runtime(tmp_path, rover, geofences=[inclusive])
    local_store.save_sweep_session(
        runtime.conn,
        {
            "id": "sess-1",
            "rover_id": "rover-1",
            "geofence_id": "fence-1",
            "status": "interrupted",
            "pattern": [
                {"order": 0, "position": {"type": "Point", "coordinates": [-85.0, 38.0]}},
                {"order": 1, "position": {"type": "Point", "coordinates": [-85.0, 38.01]}},
            ],
            "last_completed_waypoint_index": 0,
            "started_at": datetime(2026, 9, 25, 10, 0, 0, tzinfo=timezone.utc),
            "interrupted_at": datetime(2026, 9, 25, 10, 5, 0, tzinfo=timezone.utc),
            "completed_at": None,
        },
    )
    local_store.save_obstacle(
        runtime.conn,
        {
            "id": "obs-pre-crash",
            "sweep_session_id": "sess-1",
            "position": (-85.0, 38.0),
            "position_uncertainty_m": 1.5,
            "type": "barrel",
            "classification_confidence": 0.9,
            "detection_method": "ultrasonic+camera",
            "status": "permanent-pending",
            "first_detected_at": datetime(2026, 9, 25, 10, 2, 0, tzinfo=timezone.utc),
            "last_confirmed_at": None,
        },
    )
    local_store.commit(runtime.conn)

    runtime.startup()

    assert runtime.sweep_session is not None
    assert runtime.sweep_session.id == "sess-1"
    assert runtime.sweep_session.status == SweepSessionStatus.IN_PROGRESS  # auto-resumed
    assert runtime.sweep_session.last_completed_waypoint_index == 0
    assert runtime._resume_validation_target == (-85.0, 38.0)  # waypoint order 0's position
    assert runtime._resume_validation_collected == []
    # The known-obstacle set is snapshotted at arm time, so it holds exactly
    # the pre-crash rows -- nothing this resume pass goes on to detect.
    assert [row["id"] for row in runtime._resume_validation_known_rows] == ["obs-pre-crash"]
    # The LCD's obstacle counter must reflect this session's history too,
    # not just what happens after this particular process restart.
    assert runtime._obstacle_count == 1
    assert runtime._last_obstacle_type == "barrel"


def _interrupted_session(session_id: str, started_at: datetime) -> dict:
    return {
        "id": session_id,
        "rover_id": "rover-1",
        "geofence_id": "fence-1",
        "status": "interrupted",
        "pattern": [
            {"order": 0, "position": {"type": "Point", "coordinates": [-85.0, 38.0]}},
            {"order": 1, "position": {"type": "Point", "coordinates": [-85.0, 38.01]}},
        ],
        "last_completed_waypoint_index": 0,
        "started_at": started_at,
        "interrupted_at": started_at,
        "completed_at": None,
    }


def test_startup_resumes_the_newest_of_several_resumable_sessions(tmp_path):
    """Regression test: list_unsynced_sweep_sessions has no ORDER BY, so
    candidates[0] was whatever SQLite happened to return first (insertion
    order) -- an old interrupted-and-unsynced session could be resumed in
    preference to a newer one, a realistic outcome after a stretch offline.
    The newest started_at must win regardless of insertion order.
    """
    rover = {"_id": "rover-1", "name": "George"}
    inclusive = {"_id": "fence-1", "type": "inclusive", "boundary": {"type": "Polygon", "coordinates": [FIELD_RING]}}
    runtime, _ = _make_runtime(tmp_path, rover, geofences=[inclusive])
    # Inserted oldest-first, so insertion order alone would pick the stale one.
    local_store.save_sweep_session(
        runtime.conn, _interrupted_session("sess-old", datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc))
    )
    local_store.save_sweep_session(
        runtime.conn, _interrupted_session("sess-new", datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc))
    )
    local_store.commit(runtime.conn)

    runtime.startup()

    assert runtime.sweep_session is not None
    assert runtime.sweep_session.id == "sess-new"
    assert runtime._obstacle_count == 0  # no obstacle rows persisted for this session


def test_startup_warns_about_the_resumable_sessions_it_skips(tmp_path):
    rover = {"_id": "rover-1", "name": "George"}
    inclusive = {"_id": "fence-1", "type": "inclusive", "boundary": {"type": "Polygon", "coordinates": [FIELD_RING]}}
    runtime, _ = _make_runtime(tmp_path, rover, geofences=[inclusive])
    local_store.save_sweep_session(
        runtime.conn, _interrupted_session("sess-old", datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc))
    )
    local_store.save_sweep_session(
        runtime.conn, _interrupted_session("sess-new", datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc))
    )
    local_store.commit(runtime.conn)

    logger = logging.getLogger("papaya_mission.runtime")
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append
    logger.addHandler(handler)
    try:
        runtime.startup()
    finally:
        logger.removeHandler(handler)

    warnings = [r.getMessage() for r in records if r.levelno == logging.WARNING]
    assert any("sess-new" in m and "sess-old" in m for m in warnings)


def test_startup_does_not_warn_about_a_single_resumable_session(tmp_path):
    rover = {"_id": "rover-1", "name": "George"}
    inclusive = {"_id": "fence-1", "type": "inclusive", "boundary": {"type": "Polygon", "coordinates": [FIELD_RING]}}
    runtime, _ = _make_runtime(tmp_path, rover, geofences=[inclusive])
    local_store.save_sweep_session(
        runtime.conn, _interrupted_session("sess-only", datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc))
    )
    local_store.commit(runtime.conn)

    logger = logging.getLogger("papaya_mission.runtime")
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append
    logger.addHandler(handler)
    try:
        runtime.startup()
    finally:
        logger.removeHandler(handler)

    assert [r for r in records if r.levelno >= logging.WARNING] == []
    assert runtime.sweep_session.id == "sess-only"


def test_startup_does_not_resume_a_completed_but_unsynced_session(tmp_path):
    rover = {"_id": "rover-1", "name": "George"}
    runtime, _ = _make_runtime(tmp_path, rover, geofences=[])
    local_store.save_sweep_session(
        runtime.conn,
        {
            "id": "sess-1",
            "rover_id": "rover-1",
            "geofence_id": "fence-1",
            "status": "completed",
            "pattern": [{"order": 0, "position": {"type": "Point", "coordinates": [-85.0, 38.0]}}],
            "last_completed_waypoint_index": 0,
            "started_at": datetime(2026, 9, 25, 10, 0, 0, tzinfo=timezone.utc),
            "interrupted_at": None,
            "completed_at": datetime(2026, 9, 25, 10, 30, 0, tzinfo=timezone.utc),
        },
    )
    local_store.commit(runtime.conn)

    runtime.startup()

    assert runtime.sweep_session is None


def test_resume_seeds_last_obstacle_type_using_confirmed_time_when_available(tmp_path):
    """Regression test: a session can have a mix of never-re-detected
    obstacles (last_confirmed_at=None) and re-confirmed ones
    (last_confirmed_at set). Ordering by last_confirmed_at alone would
    raise TypeError comparing None to a real datetime -- the fallback to
    first_detected_at must apply per-obstacle, not just when ALL rows
    lack a confirmation time.
    """
    rover = {"_id": "rover-1", "name": "George"}
    inclusive = {"_id": "fence-1", "type": "inclusive", "boundary": {"type": "Polygon", "coordinates": [FIELD_RING]}}
    runtime, _ = _make_runtime(tmp_path, rover, geofences=[inclusive])
    local_store.save_sweep_session(
        runtime.conn, _interrupted_session("sess-1", datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc))
    )
    local_store.save_obstacle(
        runtime.conn,
        {
            "id": "obs-first",
            "sweep_session_id": "sess-1",
            "position": (-85.0, 38.0),
            "position_uncertainty_m": 1.5,
            "type": "barrel",
            "classification_confidence": 0.9,
            "detection_method": "ultrasonic+camera",
            "status": "permanent-pending",
            "first_detected_at": datetime(2026, 9, 25, 10, 1, 0, tzinfo=timezone.utc),
            "last_confirmed_at": None,  # never re-detected
        },
    )
    local_store.save_obstacle(
        runtime.conn,
        {
            "id": "obs-reconfirmed",
            "sweep_session_id": "sess-1",
            "position": (-85.0, 38.005),
            "position_uncertainty_m": 1.5,
            "type": "cone",
            "classification_confidence": 0.85,
            "detection_method": "ultrasonic+camera",
            "status": "permanent-pending",
            "first_detected_at": datetime(2026, 9, 25, 10, 0, 30, tzinfo=timezone.utc),
            "last_confirmed_at": datetime(2026, 9, 25, 10, 3, 0, tzinfo=timezone.utc),  # re-detected later
        },
    )
    local_store.commit(runtime.conn)

    runtime.startup()  # must not raise

    assert runtime._obstacle_count == 2
    # obs-reconfirmed's last_confirmed_at (10:03:00) is the most recent
    # obstacle-related event of the two -- its type wins, even though
    # obs-first's first_detected_at (10:01:00) is more recent than
    # obs-reconfirmed's OWN first_detected_at (10:00:30).
    assert runtime._last_obstacle_type == "cone"


def test_command_poll_does_not_crash_when_due(tmp_path):
    """Regression test for the flakiness fix: backdates the command-poll
    timer to force /commands/poll/rover-1 to fire deterministically on this
    tick, rather than relying on a full-suite stall to trigger it by luck.
    _make_runtime's own helper never calls tick() -- every other test in
    this file only calls startup() -- so this test drives tick() itself.
    """
    rover = {"_id": "rover-1", "name": "George"}
    inclusive = {"_id": "fence-1", "type": "inclusive", "boundary": {"type": "Polygon", "coordinates": [FIELD_RING]}}
    runtime, _ = _make_runtime(tmp_path, rover, geofences=[inclusive])
    runtime.startup()
    runtime._last_command_poll_monotonic = 0.0  # force a poll this tick

    runtime.tick()  # must not raise
