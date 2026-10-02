# pathfinder-autonomous/pi-mission/tests/test_runtime_tick_sensing.py
import logging
from datetime import datetime, timezone

import httpx
import pytest

from papaya_mission.esp32_link import BumpEvent, FakeEsp32Link, Esp32Status
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


def test_gps_never_acquired_still_triggers_stop_and_alert(tmp_path):
    """Regression test: _check_gps_loss returned immediately while
    _last_gps_fix_monotonic was None, and _read_position's dummy-seed path
    (no real fix ever received) deliberately left it None. A cold boot under
    tree cover with zero real fixes therefore NEVER evaluated GPS-loss
    safety, no matter how long dead reckoning ran or how large the error
    radius grew. "Never had a fix" now starts the same clock as "just lost
    it", so the check evaluates from the first tick onward.
    """
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = _make_started_runtime(tmp_path, sensor_hub=hub)
    assert runtime.position_fusion is None

    for _ in range(3):
        runtime.tick()  # no GPS fix is ever scripted -- pure dead reckoning

    # The dummy seed's 999m accuracy is already past
    # GPS_LOSS_MAX_ERROR_RADIUS_M, which is the honest reading: with no fix
    # ever received the rover genuinely does not know where it is.
    assert runtime._last_gps_fix_monotonic is not None
    assert runtime.mission_alert == "gps_stop_and_alert"


def test_gps_alert_clears_once_a_healthy_fix_returns(tmp_path):
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = _make_started_runtime(tmp_path, sensor_hub=hub)
    hub.script_gps_fix(GpsFix(lat=38.05, lon=-85.0, accuracy_m=2.0, timestamp=0.0))
    runtime.tick()  # seeds position_fusion from a real fix
    runtime._last_gps_fix_monotonic -= 31.0  # 31s of silence, past the grace period
    runtime.tick()
    assert runtime.mission_alert == "gps_stop_and_alert"

    # A healthy fix resets both the clock and the error radius, so the
    # condition genuinely no longer holds -- the alert must not stick.
    hub.script_gps_fix(GpsFix(lat=38.05, lon=-85.0, accuracy_m=1.0, timestamp=1.0))
    runtime.tick()

    assert runtime.mission_alert is None


def test_gps_alert_is_logged_once_on_transition_not_every_held_tick(tmp_path):
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = _make_started_runtime(tmp_path, sensor_hub=hub)
    hub.script_gps_fix(GpsFix(lat=38.05, lon=-85.0, accuracy_m=2.0, timestamp=0.0))
    runtime.tick()
    runtime._last_gps_fix_monotonic -= 31.0

    logger = logging.getLogger("papaya_mission.runtime")
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append
    logger.addHandler(handler)
    try:
        for _ in range(3):  # alert raised on the first, held on the rest
            runtime.tick()
    finally:
        logger.removeHandler(handler)

    errors = [r for r in records if r.levelno == logging.ERROR]
    assert len(errors) == 1  # logged on the transition in, not at tick rate
    assert "GPS loss safety triggered" in errors[0].getMessage()


def test_mission_alert_is_reported_in_telemetry(tmp_path):
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = _make_started_runtime(tmp_path, sensor_hub=hub)
    hub.script_gps_fix(GpsFix(lat=38.05, lon=-85.0, accuracy_m=2.0, timestamp=0.0))
    runtime.tick()
    runtime._last_gps_fix_monotonic -= 31.0

    runtime._last_telemetry_sample_monotonic = 0.0  # force a sample this tick
    runtime.tick()

    metrics = local_store.list_unsynced_telemetry(runtime.conn)[-1]["metrics"]
    assert metrics["mission_alert"] == "gps_stop_and_alert"


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


def test_exclusion_alert_clears_once_the_rover_leaves_the_zone(tmp_path):
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

    # Driven back out of the pond -- the condition no longer holds, so the
    # alert must not stay latched for the rest of the process.
    hub.script_gps_fix(GpsFix(lat=38.06, lon=-85.0, accuracy_m=2.0, timestamp=1.0))
    runtime.tick()

    assert runtime.mission_alert is None


class _RaisingSource:
    """A sensor source whose read() always raises, standing in for a flaky
    real driver. The Protocols ask drivers not to raise, but MissionRuntime
    must not depend on that -- per the Global Constraint, a failure reading
    one sensor must never stop the mission.
    """

    def __init__(self, message: str) -> None:
        self._message = message

    def read(self):
        raise RuntimeError(self._message)


def test_a_raising_gps_read_does_not_stop_the_tick(tmp_path):
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = _make_started_runtime(tmp_path, sensor_hub=hub)
    hub.gps = _RaisingSource("gps uart timeout")

    runtime.tick()  # must not raise
    runtime.tick()

    # Position still tracked -- the IMU read succeeded, so dead reckoning
    # continues exactly as it would during a normal GPS outage.
    assert runtime.position_fusion is not None


def test_a_raising_imu_read_skips_the_position_step_without_crashing(tmp_path):
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = _make_started_runtime(tmp_path, sensor_hub=hub)
    hub.imu = _RaisingSource("imu i2c nak")

    runtime.tick()  # must not raise

    # Nothing to seed from, so there is no estimate this tick -- but the tick
    # itself completed, and every position-dependent step was skipped rather
    # than dereferencing a None fusion.
    assert runtime.position_fusion is None


def test_raising_obstacle_sensors_and_bump_poll_do_not_stop_the_tick(tmp_path):
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = _make_started_runtime(tmp_path, sensor_hub=hub)
    hub.script_gps_fix(GpsFix(lat=38.05, lon=-85.0, accuracy_m=2.0, timestamp=0.0))
    runtime.tick()  # seed position_fusion normally

    hub.ultrasonic = _RaisingSource("ultrasonic echo timeout")
    hub.camera = _RaisingSource("camera pipeline stalled")

    def _boom():
        raise RuntimeError("esp32 link dropped")

    runtime.esp32_link.poll_bump_events = _boom
    runtime.esp32_link.read_drive_status = _boom
    runtime._last_telemetry_sample_monotonic = 0.0  # force a telemetry sample too

    runtime.tick()  # must not raise

    # Telemetry was still written, with the unreadable drive metrics tagged
    # "missing" rather than the whole sample being lost.
    metrics = local_store.list_unsynced_telemetry(runtime.conn)[-1]["metrics"]
    assert metrics["throttle_position"] == "missing"
    assert metrics["position"] != "missing"  # position was readable, so it is real


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


def test_two_known_obstacles_at_one_position_keep_separate_identities(tmp_path):
    """The resume-validation id lookup keys rows by
    (position, type, detection_method, first_detected_at), not position alone,
    so two obstacles at a bit-identical position -- a bump contact and an
    ultrasonic detection logged at the same stationary rover position -- cannot
    have their ids conflated when only one of them is confirmed.

    Characterization test, not a red-then-green regression test: with the key
    and the lookup both derived from the same ordered row list, the old
    position-only key happened to agree, so this passes before and after. It
    locks in the invariant the tuple key makes structural instead of
    incidental -- exactly one row refreshed, the other untouched, and no
    duplicate row minted.
    """
    hub = SimulatedSensorHub(INITIAL_IMU)
    bump_twin = _known_obstacle("obs-bump", RESUME_WAYPOINT_POSITION) | {
        "id": "obs-bump",
        "type": "unknown",
        "detection_method": "contact-only",
        "classification_confidence": 0.0,
        "first_detected_at": datetime(2026, 9, 25, 10, 3, 0, tzinfo=timezone.utc),
    }
    runtime = _make_resumed_runtime(
        tmp_path,
        hub,
        [_known_obstacle("obs-paired", RESUME_WAYPOINT_POSITION), bump_twin],
    )
    assert len(runtime._resume_validation_known_rows) == 2

    # Arrive at the resume target and re-detect ONE obstacle at that position.
    hub.script_gps_fix(GpsFix(lat=38.0, lon=-85.0, accuracy_m=2.0, timestamp=0.0))
    hub.script_ultrasonic(ObstacleDetection(relative_bearing_deg=0.0, range_m=0.0))
    hub.script_camera(("barrel", 0.9))
    runtime.tick()

    rows = local_store.list_obstacles_for_session(runtime.conn, "sess-1")
    # No third row minted: the re-detection reused one of the two known ids.
    assert sorted(r["id"] for r in rows) == ["obs-bump", "obs-paired"]
    # Exactly one row refreshed -- the id lookup consumed one id, not both and
    # not the same one twice.
    refreshed = [r["id"] for r in rows if r["last_confirmed_at"] is not None]
    assert len(refreshed) == 1
    # Whichever row was confirmed, the OTHER one's distinguishing fields are
    # intact -- an upsert under a conflated id would have overwritten them.
    by_id = {r["id"]: r for r in rows}
    assert by_id["obs-bump"]["detection_method"] == "contact-only"
    assert by_id["obs-bump"]["first_detected_at"] == datetime(2026, 9, 25, 10, 3, 0, tzinfo=timezone.utc)
    assert by_id["obs-paired"]["detection_method"] == "ultrasonic+camera"
    assert by_id["obs-paired"]["first_detected_at"] == PRE_CRASH_DETECTED_AT


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


def test_last_telemetry_readings_starts_empty_before_any_sample(tmp_path):
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = _make_started_runtime(tmp_path, sensor_hub=hub)

    # startup() arms _last_telemetry_sample_monotonic to "now", so the very
    # first tick's sample is not yet due -- nothing has been snapshotted yet.
    assert runtime.last_telemetry_readings == {}


def test_last_telemetry_readings_reflects_latest_sample(tmp_path):
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = _make_started_runtime(tmp_path, sensor_hub=hub)
    hub.script_gps_fix(GpsFix(lat=38.05, lon=-85.0, accuracy_m=2.0, timestamp=0.0))
    runtime._last_telemetry_sample_monotonic = 0.0  # force a sample this tick

    runtime.tick()

    assert runtime.last_telemetry_readings["position"] == [-85.0, 38.05]
    assert runtime.last_telemetry_readings["mission_alert"] == "none"
    assert runtime.last_telemetry_readings["halted_on_contact"] is False  # FakeEsp32Link's default status


def test_last_telemetry_readings_includes_halted_on_contact_when_true(tmp_path):
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = _make_started_runtime(tmp_path, sensor_hub=hub)
    hub.script_gps_fix(GpsFix(lat=38.05, lon=-85.0, accuracy_m=2.0, timestamp=0.0))
    runtime.esp32_link.script_status(Esp32Status(halted_on_contact=True))
    runtime._last_telemetry_sample_monotonic = 0.0

    runtime.tick()

    assert runtime.last_telemetry_readings["halted_on_contact"] is True


def test_a_raising_esp32_status_read_leaves_halted_on_contact_out_of_the_sample(tmp_path):
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = _make_started_runtime(tmp_path, sensor_hub=hub)
    hub.script_gps_fix(GpsFix(lat=38.05, lon=-85.0, accuracy_m=2.0, timestamp=0.0))

    def _boom():
        raise RuntimeError("esp32 link dropped")

    runtime.esp32_link.status = _boom
    runtime._last_telemetry_sample_monotonic = 0.0

    runtime.tick()  # must not raise

    assert "halted_on_contact" not in runtime.last_telemetry_readings
    assert runtime.last_telemetry_readings["position"] == [-85.0, 38.05]  # rest of the sample is unaffected


def test_obstacle_count_increments_on_a_bump_contact(tmp_path):
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = _make_started_runtime(tmp_path, sensor_hub=hub)
    hub.script_gps_fix(GpsFix(lat=38.05, lon=-85.0, accuracy_m=2.0, timestamp=0.0))
    runtime.tick()  # seeds position_fusion
    assert runtime._obstacle_count == 0

    runtime.esp32_link.script_bump_events([BumpEvent(detected_at=datetime(2026, 9, 25, tzinfo=timezone.utc))])
    runtime._last_telemetry_sample_monotonic = 0.0  # force a sample this tick
    runtime.tick()

    assert runtime._obstacle_count == 1
    assert runtime._last_obstacle_type == "unknown"  # obstacle_from_bump_contact's type
    assert runtime.last_telemetry_readings["obstacle_count"] == 1
    assert runtime.last_telemetry_readings["last_obstacle_type"] == "unknown"


def test_obstacle_count_increments_even_with_no_active_sweep_session(tmp_path):
    """A bump contact with no sweep session active still makes
    _save_obstacle return early WITHOUT writing a row (see its own
    docstring/comments) -- the counter must still increment, since the
    rover genuinely reacted to something. Only the durable row is skipped.
    """
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = _make_started_runtime(tmp_path, sensor_hub=hub)
    hub.script_gps_fix(GpsFix(lat=38.05, lon=-85.0, accuracy_m=2.0, timestamp=0.0))
    runtime.tick()
    runtime.sweep_session = None  # simulate no active session

    runtime.esp32_link.script_bump_events([BumpEvent(detected_at=datetime(2026, 9, 25, tzinfo=timezone.utc))])
    runtime.tick()

    assert runtime._obstacle_count == 1
    assert local_store.list_unsynced_obstacles(runtime.conn) == []  # not persisted -- no session to attach to
