# pathfinder-autonomous/pi-mission/tests/test_runtime_tick_sensing.py
from datetime import datetime, timezone

import httpx
import pytest

from papaya_mission.esp32_link import BumpEvent, FakeEsp32Link
from papaya_mission.position_fusion import GpsFix, ImuReading
from papaya_mission.runtime import MissionRuntime
from papaya_mission.sensor_hub import ObstacleDetection, SimulatedSensorHub
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
            return httpx.Response(200, json=next(g for g in geofences if g["_id"] == fid))
        raise AssertionError(request.url.path)

    return handler


def _make_started_runtime(tmp_path, sensor_hub=None) -> MissionRuntime:
    rover = {"_id": "rover-1", "name": "George", "length_m": 0.6, "turn_style": "spin_in_place"}
    inclusive = {"_id": "fence-1", "type": "inclusive", "boundary": {"type": "Polygon", "coordinates": [FIELD_RING]}}
    client = httpx.Client(transport=httpx.MockTransport(_handler(rover, [inclusive])))
    runtime = MissionRuntime(
        rover_id="rover-1",
        backend_base_url="http://backend.local",
        local_db_path=str(tmp_path / "test.db"),
        sensor_hub=sensor_hub or SimulatedSensorHub(INITIAL_IMU),
        esp32_link=FakeEsp32Link(),
        http_client=client,
    )
    runtime.startup()
    runtime.handle_start_sweep({"geofence_id": "fence-1"})
    return runtime


def test_tick_updates_position_from_imu(tmp_path):
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = _make_started_runtime(tmp_path, sensor_hub=hub)
    initial_fix = GpsFix(lat=38.05, lon=-85.0, accuracy_m=2.0, timestamp=0.0)
    runtime.position_fusion = None  # not yet seeded -- tick() seeds it from the first GPS fix
    hub.script_gps_fix(initial_fix)

    runtime.tick()

    assert runtime.position_fusion is not None
    assert runtime.position_fusion.current_estimate.lat == 38.05


def test_tick_creates_obstacle_from_paired_ultrasonic_and_camera_detection(tmp_path):
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = _make_started_runtime(tmp_path, sensor_hub=hub)
    hub.script_gps_fix(GpsFix(lat=38.05, lon=-85.0, accuracy_m=2.0, timestamp=0.0))
    runtime.tick()  # seeds position_fusion

    hub.script_ultrasonic(ObstacleDetection(relative_bearing_deg=0.0, range_m=2.0))
    hub.script_camera(("barrel", 0.9))

    runtime.tick()

    saved = local_store.list_unsynced_obstacles(runtime.conn)
    assert len(saved) == 1
    assert saved[0]["type"] == "barrel"
    assert saved[0]["status"] == "permanent-pending"


def test_tick_creates_obstacle_from_bump_contact(tmp_path):
    esp32 = FakeEsp32Link()
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = _make_started_runtime(tmp_path, sensor_hub=hub)
    runtime.esp32_link = esp32
    hub.script_gps_fix(GpsFix(lat=38.05, lon=-85.0, accuracy_m=2.0, timestamp=0.0))
    runtime.tick()

    esp32.script_bump_events([BumpEvent(detected_at=datetime(2026, 9, 25, tzinfo=timezone.utc))])

    runtime.tick()

    saved = local_store.list_unsynced_obstacles(runtime.conn)
    assert len(saved) == 1
    assert saved[0]["detection_method"] == "contact-only"


def test_gps_loss_past_grace_period_sets_stop_and_alert(tmp_path):
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = _make_started_runtime(tmp_path, sensor_hub=hub)
    hub.script_gps_fix(GpsFix(lat=38.05, lon=-85.0, accuracy_m=2.0, timestamp=0.0))
    runtime.tick()  # seeds position_fusion, last GPS fix at monotonic ~now

    runtime._last_gps_fix_monotonic -= 31.0  # simulate 31s of GPS silence, past the 30s grace period

    runtime.tick()

    assert runtime.mission_alert == "gps_stop_and_alert"


def test_exclusion_intrusion_sets_wait_for_help_when_deep(tmp_path):
    pond_ring = [[-85.001, 38.049], [-85.001, 38.051], [-84.999, 38.051], [-84.999, 38.049], [-85.001, 38.049]]
    rover = {"_id": "rover-1", "name": "George", "length_m": 0.6, "turn_style": "spin_in_place"}
    inclusive = {"_id": "fence-1", "type": "inclusive", "boundary": {"type": "Polygon", "coordinates": [FIELD_RING]}}
    exclusive = {"_id": "fence-2", "type": "exclusive", "boundary": {"type": "Polygon", "coordinates": [pond_ring]}}
    client = httpx.Client(transport=httpx.MockTransport(_handler(rover, [inclusive, exclusive])))
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = MissionRuntime(
        rover_id="rover-1", backend_base_url="http://backend.local",
        local_db_path=str(tmp_path / "test.db"), sensor_hub=hub, esp32_link=FakeEsp32Link(), http_client=client,
    )
    runtime.startup()
    runtime.handle_start_sweep({"geofence_id": "fence-1"})

    hub.script_gps_fix(GpsFix(lat=38.05, lon=-85.0, accuracy_m=2.0, timestamp=0.0))
    runtime.tick()

    assert runtime.mission_alert == "exclusion_wait_for_help"


RESUME_WAYPOINT_POSITION = (-85.0, 38.0)
PRE_CRASH_DETECTED_AT = datetime(2026, 9, 25, 10, 2, 0, tzinfo=timezone.utc)


def _known_obstacle(obstacle_id: str, position: tuple[float, float]) -> dict:
    return {
        "id": obstacle_id,
        "sweep_session_id": "sess-1",
        "position": position,
        "position_uncertainty_m": 1.5,
        "type": "barrel",
        "classification_confidence": 0.9,
        "detection_method": "ultrasonic+camera",
        "status": "permanent-pending",
        "first_detected_at": PRE_CRASH_DETECTED_AT,
        "last_confirmed_at": None,
    }


def _make_resumed_runtime(tmp_path, hub, known_obstacles, esp32_link=None) -> MissionRuntime:
    """A runtime whose local store already holds an interrupted sweep session
    (last completed waypoint = order 0 at RESUME_WAYPOINT_POSITION) plus
    `known_obstacles`, started up so the crash-recovery path arms
    resume-validation and snapshots those obstacles as the known set.
    """
    rover = {"_id": "rover-1", "name": "George", "length_m": 0.6, "turn_style": "spin_in_place"}
    inclusive = {"_id": "fence-1", "type": "inclusive", "boundary": {"type": "Polygon", "coordinates": [FIELD_RING]}}
    client = httpx.Client(transport=httpx.MockTransport(_handler(rover, [inclusive])))
    runtime = MissionRuntime(
        rover_id="rover-1", backend_base_url="http://backend.local",
        local_db_path=str(tmp_path / "test.db"), sensor_hub=hub,
        esp32_link=esp32_link or FakeEsp32Link(), http_client=client,
    )
    local_store.save_sweep_session(
        runtime.conn,
        {
            "id": "sess-1",
            "rover_id": "rover-1",
            "geofence_id": "fence-1",
            "status": "interrupted",
            "pattern": [
                {"order": 0, "position": {"type": "Point", "coordinates": list(RESUME_WAYPOINT_POSITION)}},
                {"order": 1, "position": {"type": "Point", "coordinates": [-85.0, 38.01]}},
            ],
            "last_completed_waypoint_index": 0,
            "started_at": datetime(2026, 9, 25, 10, 0, 0, tzinfo=timezone.utc),
            "interrupted_at": datetime(2026, 9, 25, 10, 5, 0, tzinfo=timezone.utc),
            "completed_at": None,
        },
    )
    for obstacle in known_obstacles:
        local_store.save_obstacle(runtime.conn, obstacle)
    local_store.commit(runtime.conn)

    runtime.startup()  # auto-resumes; arms resume-validation and snapshots known rows
    return runtime


def test_resume_validation_reconciles_against_snapshot_not_a_contaminated_live_query(tmp_path):
    """Regression test for the snapshot-vs-live-query design in
    _resume_in_progress_session_if_any (Task 6) / _check_resume_validation_arrival
    (Task 7). A fresh obstacle row that lands in the local store mid-pass must
    not contaminate the known-obstacle set used to reconcile the eventual
    re-detection of the pre-crash obstacle. If reconciliation re-queried the
    store live instead of using the ._resume_validation_known_rows snapshot
    taken at arm time, that fresh row would show up in the "known" set right
    alongside the real pre-crash obstacle, and greedy nearest-first matching
    would let it claim the re-detection.

    Paired ultrasonic+camera detections are now DEFERRED while a resume pass is
    armed, so they no longer reach the store before reconciliation. Bump
    contacts still persist immediately, though -- they are a reactive source
    outside resume-validation reconciliation entirely -- so they are what keeps
    the snapshot load-bearing, and what this test uses as its decoy.
    """
    hub = SimulatedSensorHub(INITIAL_IMU)
    esp32 = FakeEsp32Link()
    # The pre-crash obstacle sits ~2.2m north of the resume waypoint, so a bump
    # row logged at the waypoint itself is strictly CLOSER to the re-detection
    # than the real pre-crash obstacle is -- the ordering that makes a live
    # query actually lose.
    runtime = _make_resumed_runtime(
        tmp_path, hub, [_known_obstacle("obs-pre-crash", (-85.0, 38.00002))], esp32_link=esp32
    )
    assert runtime._resume_validation_target == RESUME_WAYPOINT_POSITION
    assert [row["id"] for row in runtime._resume_validation_known_rows] == ["obs-pre-crash"]

    # Tick 1: the rover is far from the resume-validation target (still
    # transiting back), so reconciliation must not fire yet. The fresh,
    # unrelated paired detection made here is DEFERRED -- collected, not
    # persisted -- because a resume pass is armed: reconciliation, not
    # _detect_obstacles, decides what id it eventually gets.
    hub.script_gps_fix(GpsFix(lat=38.05, lon=-85.0, accuracy_m=2.0, timestamp=0.0))
    hub.script_ultrasonic(ObstacleDetection(relative_bearing_deg=0.0, range_m=2.0))
    hub.script_camera(("cone", 0.8))
    runtime.tick()

    rows_after_tick1 = local_store.list_obstacles_for_session(runtime.conn, "sess-1")
    assert [r["id"] for r in rows_after_tick1] == ["obs-pre-crash"]  # decoy deferred, not saved
    assert len(runtime._resume_validation_collected) == 1
    assert runtime._resume_validation_target is not None  # not yet reconciled -- still far away

    # Tick 2: the rover arrives back at the resume-validation target and
    # re-detects what is really the SAME obstacle the pre-crash session already
    # knew about. It also logs a bump contact at its own position -- a row that
    # lands in the store on this very tick, 0m from the fresh re-detection.
    hub.script_gps_fix(GpsFix(lat=38.0, lon=-85.0, accuracy_m=2.0, timestamp=1.0))
    hub.script_ultrasonic(ObstacleDetection(relative_bearing_deg=0.0, range_m=0.0))
    hub.script_camera(("barrel", 0.9))
    esp32.script_bump_events([BumpEvent(detected_at=datetime(2026, 9, 25, 10, 30, tzinfo=timezone.utc))])
    runtime.tick()

    assert runtime._resume_validation_target is None  # reconciled and cleared

    rows_after_tick2 = local_store.list_obstacles_for_session(runtime.conn, "sess-1")
    pre_crash_row = next(r for r in rows_after_tick2 if r["id"] == "obs-pre-crash")
    # The re-detection must have been reconciled by reusing "obs-pre-crash"'s
    # own id -- an upsert in place (first_detected_at unchanged,
    # last_confirmed_at now set) -- not by minting a fresh id for it, and not
    # crowded out by the same-tick bump row a live query would have included.
    assert pre_crash_row["first_detected_at"] == PRE_CRASH_DETECTED_AT
    assert pre_crash_row["last_confirmed_at"] is not None

    bump_row = next(r for r in rows_after_tick2 if r["detection_method"] == "contact-only")
    assert bump_row["last_confirmed_at"] is None  # never a reconciliation input

    decoy_rows = [
        r for r in rows_after_tick2
        if r["id"] != "obs-pre-crash" and r["detection_method"] == "ultrasonic+camera"
    ]
    # The tick-1 decoy was genuinely new, so reconciliation persisted it once,
    # with a fresh id -- never confirmed against the obstacle it isn't near.
    assert len(decoy_rows) == 1
    assert decoy_rows[0]["type"] == "cone"
    assert decoy_rows[0]["last_confirmed_at"] is None


def test_confirmed_redetection_during_resume_pass_saves_exactly_one_row(tmp_path):
    """Regression test for the duplicate-row bug. A re-detection during a
    resume pass must leave exactly ONE row, under the known obstacle's existing
    id. The old code saved the fresh detection immediately with a new uuid AND
    then upserted the confirmed match under the known id, leaving two rows for
    one physical obstacle -- both synced to the backend as separate documents,
    with the extra one reported as a bogus "vanished" discrepancy on the next
    resume pass.
    """
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = _make_resumed_runtime(
        tmp_path, hub, [_known_obstacle("obs-pre-crash", RESUME_WAYPOINT_POSITION)]
    )

    # Arrive at the resume target and re-detect the obstacle at its own position.
    hub.script_gps_fix(GpsFix(lat=38.0, lon=-85.0, accuracy_m=2.0, timestamp=0.0))
    hub.script_ultrasonic(ObstacleDetection(relative_bearing_deg=0.0, range_m=0.0))
    hub.script_camera(("barrel", 0.9))
    runtime.tick()

    assert runtime._resume_validation_target is None  # reconciled

    rows = local_store.list_obstacles_for_session(runtime.conn, "sess-1")
    assert [r["id"] for r in rows] == ["obs-pre-crash"]  # one row, the original id
    assert rows[0]["last_confirmed_at"] is not None  # refreshed in place
    assert rows[0]["first_detected_at"] == PRE_CRASH_DETECTED_AT
    assert len(local_store.list_unsynced_obstacles(runtime.conn)) == 1


def test_resume_validation_reconciles_on_arrival_even_with_no_detection(tmp_path):
    """Reconciliation is its own tick step, not a side effect of a paired
    detection. Arriving at the resume target having detected NOTHING must still
    reconcile -- that "the obstacle is genuinely gone" case is the whole point
    of resume validation. Under the old code reconciliation was only reachable
    from inside _detect_obstacles' paired-detection branch, so a silent arrival
    never reconciled at all and the resume pass stayed armed forever.
    """
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = _make_resumed_runtime(
        tmp_path, hub, [_known_obstacle("obs-pre-crash", RESUME_WAYPOINT_POSITION)]
    )

    # Arrive at the resume target with no ultrasonic/camera pair and no bump.
    hub.script_gps_fix(GpsFix(lat=38.0, lon=-85.0, accuracy_m=2.0, timestamp=0.0))
    runtime.tick()

    assert runtime._resume_validation_target is None  # reconciliation ran and reset state
    assert runtime._resume_validation_collected == []
    assert runtime._resume_validation_known_rows == []

    # Nothing re-detected: the known obstacle is untouched, surfaced as a
    # discrepancy for operator review rather than confirmed.
    rows = local_store.list_obstacles_for_session(runtime.conn, "sess-1")
    assert [r["id"] for r in rows] == ["obs-pre-crash"]
    assert rows[0]["last_confirmed_at"] is None
