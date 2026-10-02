import logging
from datetime import datetime, timezone

import httpx

from papaya_mission.esp32_link import DriveStatus, Esp32Status, FakeEsp32Link
from papaya_mission.position_fusion import GpsFix, ImuReading
from papaya_mission.runtime import MissionRuntime
from papaya_mission.sensor_hub import SimulatedSensorHub
from papaya_mission.sweep_session import SweepSessionStatus

INITIAL_IMU = ImuReading(heading_deg=0.0, forward_acceleration_mps2=0.0, timestamp=0.0)
FIELD_RING = [[-85.10, 38.00], [-85.10, 38.10], [-84.90, 38.10], [-84.90, 38.00], [-85.10, 38.00]]


def _handler(rover, geofences, commands, acked):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rovers/rover-1":
            return httpx.Response(200, json=rover)
        if request.url.path == "/geofences":
            return httpx.Response(200, json=geofences)
        if request.url.path.startswith("/geofences/"):
            fid = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, json=next(g for g in geofences if g["_id"] == fid))
        if request.url.path == "/commands/poll/rover-1":
            pending, commands[:] = commands[:], []
            return httpx.Response(200, json=pending)
        if request.url.path.startswith("/commands/") and request.url.path.endswith("/ack"):
            acked.append(request.url.path)
            return httpx.Response(200, json={"status": "acked"})
        raise AssertionError(request.url.path)

    return handler


def _make_started_runtime(tmp_path, commands, acked) -> MissionRuntime:
    rover = {"_id": "rover-1", "name": "George", "length_m": 0.6, "turn_style": "spin_in_place"}
    inclusive = {"_id": "fence-1", "type": "inclusive", "boundary": {"type": "Polygon", "coordinates": [FIELD_RING]}}
    client = httpx.Client(transport=httpx.MockTransport(_handler(rover, [inclusive], commands, acked)))
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = MissionRuntime(
        rover_id="rover-1", backend_base_url="http://backend.local",
        local_db_path=str(tmp_path / "test.db"), sensor_hub=hub, esp32_link=FakeEsp32Link(), http_client=client,
    )
    runtime.startup()
    runtime.handle_start_sweep({"geofence_id": "fence-1"})
    hub.script_gps_fix(GpsFix(lat=38.05, lon=-85.0, accuracy_m=2.0, timestamp=0.0))
    runtime._last_telemetry_sample_monotonic = float("inf")  # no telemetry sample on the seed tick
    runtime.tick()  # seed position_fusion
    return runtime


def _make_idle_runtime(tmp_path, commands, acked) -> MissionRuntime:
    """A started-up runtime with NO sweep session -- handle_start_sweep is
    deliberately never called, so a sweep can only begin via a start_sweep
    command travelling the real poll -> dispatch path.
    """
    rover = {"_id": "rover-1", "name": "George", "length_m": 0.6, "turn_style": "spin_in_place"}
    inclusive = {"_id": "fence-1", "type": "inclusive", "boundary": {"type": "Polygon", "coordinates": [FIELD_RING]}}
    client = httpx.Client(transport=httpx.MockTransport(_handler(rover, [inclusive], commands, acked)))
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = MissionRuntime(
        rover_id="rover-1", backend_base_url="http://backend.local",
        local_db_path=str(tmp_path / "test.db"), sensor_hub=hub, esp32_link=FakeEsp32Link(), http_client=client,
    )
    runtime.startup()
    hub.script_gps_fix(GpsFix(lat=38.05, lon=-85.0, accuracy_m=2.0, timestamp=0.0))
    runtime._last_command_poll_monotonic = float("inf")  # seed position without polling
    runtime._last_telemetry_sample_monotonic = float("inf")  # no telemetry sample on the seed tick
    runtime.tick()
    return runtime


def test_start_sweep_command_is_dispatched_through_the_command_poll_path(tmp_path):
    """Regression test: handle_start_sweep existed and worked, but
    _handle_command had no start_sweep branch, so a start_sweep polled from
    the backend fell through every branch and was acked as if handled --
    the rover reported active with no sweep ever starting. This test drives
    it through _poll_and_handle_commands_if_due -> _handle_command rather
    than calling handle_start_sweep directly, which is the only way that
    gap was observable.
    """
    commands = [{"_id": "cmd-1", "type": "start_sweep", "payload": {"geofence_id": "fence-1"}}]
    acked = []
    runtime = _make_idle_runtime(tmp_path, commands, acked)
    assert runtime.sweep_session is None
    runtime._last_command_poll_monotonic = 0.0  # force a poll this tick

    runtime.tick()

    assert runtime.sweep_session is not None
    assert runtime.sweep_session.geofence_id == "fence-1"
    assert runtime.sweep_session.status == SweepSessionStatus.IN_PROGRESS
    assert acked == ["/commands/cmd-1/ack"]


def test_unrecognized_command_type_is_logged_rather_than_silently_ignored(tmp_path):
    commands = [{"_id": "cmd-1", "type": "do_a_barrel_roll", "payload": {}}]
    acked = []
    runtime = _make_idle_runtime(tmp_path, commands, acked)
    runtime._last_command_poll_monotonic = 0.0

    logger = logging.getLogger("papaya_mission.runtime")
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append
    logger.addHandler(handler)
    try:
        runtime.tick()
    finally:
        logger.removeHandler(handler)

    assert any(
        record.levelno == logging.WARNING and "do_a_barrel_roll" in record.getMessage()
        for record in records
    )
    assert acked == ["/commands/cmd-1/ack"]


def test_malformed_command_does_not_stop_the_tick_or_the_rest_of_the_batch(tmp_path):
    """Fault isolation is about failures generally, not HTTP failures
    specifically: a command dict with no "type" raises KeyError inside
    _handle_command, which the old httpx.HTTPError-only guard let escape
    and kill the whole tick (and every later command in the batch).
    """
    commands = [
        {"_id": "cmd-bad", "payload": {}},  # no "type" -> KeyError in _handle_command
        {"_id": "cmd-2", "type": "pause_sweep", "payload": {}},
    ]
    acked = []
    runtime = _make_started_runtime(tmp_path, commands, acked)
    runtime._last_command_poll_monotonic = 0.0

    runtime.tick()  # must not raise

    assert runtime.sweep_session.status == SweepSessionStatus.INTERRUPTED  # cmd-2 still ran
    assert acked == ["/commands/cmd-2/ack"]  # the malformed one was never acked


def test_start_sweep_with_a_malformed_payload_does_not_raise_out_of_tick(tmp_path):
    """start_sweep's own failure modes are KeyError (no geofence_id) and
    ValueError (derive_row_spacing_m rejecting the rover's turn geometry) --
    neither an httpx.HTTPError, both now covered by the broadened guard.
    """
    commands = [{"_id": "cmd-1", "type": "start_sweep", "payload": {}}]
    acked = []
    runtime = _make_idle_runtime(tmp_path, commands, acked)
    runtime._last_command_poll_monotonic = 0.0

    runtime.tick()  # must not raise

    assert runtime.sweep_session is None
    assert acked == []  # never acked, so the backend can redeliver it


def test_pause_command_interrupts_sweep_session_and_acks(tmp_path):
    commands = [{"_id": "cmd-1", "type": "pause_sweep", "payload": {}}]
    acked = []
    runtime = _make_started_runtime(tmp_path, commands, acked)
    runtime._last_command_poll_monotonic = 0.0  # force a poll this tick

    runtime.tick()

    assert runtime.sweep_session.status == SweepSessionStatus.INTERRUPTED
    assert acked == ["/commands/cmd-1/ack"]


def test_resume_command_resumes_sweep_session(tmp_path):
    commands = [{"_id": "cmd-1", "type": "pause_sweep", "payload": {}}]
    acked = []
    runtime = _make_started_runtime(tmp_path, commands, acked)
    runtime._last_command_poll_monotonic = 0.0
    runtime.tick()
    assert runtime.sweep_session.status == SweepSessionStatus.INTERRUPTED

    commands.append({"_id": "cmd-2", "type": "resume_sweep", "payload": {}})
    runtime._last_command_poll_monotonic = 0.0
    runtime.tick()

    assert runtime.sweep_session.status == SweepSessionStatus.IN_PROGRESS


def test_resume_command_treats_halted_esp32_as_a_bump_event_instead(tmp_path):
    commands = [{"_id": "cmd-1", "type": "pause_sweep", "payload": {}}]
    acked = []
    runtime = _make_started_runtime(tmp_path, commands, acked)
    runtime._last_command_poll_monotonic = 0.0
    runtime.tick()
    runtime.esp32_link.script_status(Esp32Status(halted_on_contact=True))

    commands.append({"_id": "cmd-2", "type": "resume_sweep", "payload": {}})
    runtime._last_command_poll_monotonic = 0.0
    runtime.tick()

    # Stayed interrupted -- resume was rejected in favor of treating the
    # halted-on-contact report as a fresh bump event.
    assert runtime.sweep_session.status == SweepSessionStatus.INTERRUPTED
    from papaya_mission import local_store
    saved = local_store.list_unsynced_obstacles(runtime.conn)
    assert any(o["detection_method"] == "contact-only" for o in saved)


def test_telemetry_sampled_and_committed_on_schedule(tmp_path):
    commands, acked = [], []
    runtime = _make_started_runtime(tmp_path, commands, acked)
    runtime._last_telemetry_sample_monotonic = 0.0  # force a sample this tick
    runtime._last_command_poll_monotonic = float("inf")  # skip command poll this tick

    runtime.tick()

    from papaya_mission import local_store
    unsynced = local_store.list_unsynced_telemetry(runtime.conn)
    assert len(unsynced) == 1
    assert unsynced[0]["rover_id"] == "rover-1"
    assert unsynced[0]["metrics"]["error_radius_m"] == 2.0  # real value, not "missing"


def test_telemetry_carries_real_position_nav_and_drive_content(tmp_path):
    """Regression test: readings only ever held error_radius_m/heading_deg
    while expected_metrics held only sensor-manifest NAMES ("gps"/"imu"/...),
    so build_telemetry_record's floor-and-ceiling rule dropped every real
    reading and stored an all-"missing" record. `position` -- the primary
    live-summary metric in the design spec -- was never emitted at all.
    """
    commands, acked = [], []
    runtime = _make_started_runtime(tmp_path, commands, acked)
    runtime.esp32_link.script_drive_status(
        DriveStatus(servo_positions_deg={"fl": 12.5}, throttle_position=0.3)
    )
    runtime._last_telemetry_sample_monotonic = 0.0
    runtime._last_command_poll_monotonic = float("inf")

    runtime.tick()

    from papaya_mission import local_store
    metrics = local_store.list_unsynced_telemetry(runtime.conn)[0]["metrics"]

    estimate = runtime.position_fusion.current_estimate
    # GeoJSON [lon, lat] order, matching every other coordinate pair here.
    assert metrics["position"] == [estimate.lon, estimate.lat]
    assert metrics["position_uncertainty_m"] == estimate.error_radius_m
    assert metrics["error_radius_m"] == estimate.error_radius_m
    assert metrics["heading_deg"] == estimate.heading_deg
    assert metrics["nav_mode"] == "sweeping"
    assert metrics["waypoint_index"] == runtime.sweep_session.last_completed_waypoint_index
    # Dynamic per-servo keys survive: expected_metrics is extended with this
    # tick's real servo ids so the floor-and-ceiling rule doesn't drop them.
    assert metrics["servo_fl_deg"] == 12.5
    assert metrics["throttle_position"] == 0.3


def test_telemetry_nav_mode_is_idle_with_no_sweep_session(tmp_path):
    commands, acked = [], []
    runtime = _make_idle_runtime(tmp_path, commands, acked)
    runtime._last_telemetry_sample_monotonic = 0.0
    runtime._last_command_poll_monotonic = float("inf")

    runtime.tick()

    from papaya_mission import local_store
    metrics = local_store.list_unsynced_telemetry(runtime.conn)[0]["metrics"]
    assert metrics["nav_mode"] == "idle"
    assert metrics["waypoint_index"] == -1


def test_telemetry_nav_mode_is_interrupted_while_paused(tmp_path):
    commands = [{"_id": "cmd-1", "type": "pause_sweep", "payload": {}}]
    acked = []
    runtime = _make_started_runtime(tmp_path, commands, acked)
    runtime._last_command_poll_monotonic = 0.0
    runtime.tick()  # handles pause_sweep
    assert runtime.sweep_session.status == SweepSessionStatus.INTERRUPTED

    runtime._last_telemetry_sample_monotonic = 0.0
    runtime._last_command_poll_monotonic = float("inf")
    runtime.tick()

    from papaya_mission import local_store
    metrics = local_store.list_unsynced_telemetry(runtime.conn)[-1]["metrics"]
    assert metrics["nav_mode"] == "interrupted"


def test_waypoint_reached_marks_it_complete(tmp_path):
    commands, acked = [], []
    runtime = _make_started_runtime(tmp_path, commands, acked)
    first_waypoint = runtime.sweep_session.pattern[0]
    lon, lat = first_waypoint.position
    runtime.sensor_hub.script_gps_fix(GpsFix(lat=lat, lon=lon, accuracy_m=1.0, timestamp=1.0))

    runtime.tick()

    assert runtime.sweep_session.last_completed_waypoint_index == 0


def _handler_poll_fails(rover, geofences):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rovers/rover-1":
            return httpx.Response(200, json=rover)
        if request.url.path == "/geofences":
            return httpx.Response(200, json=geofences)
        if request.url.path.startswith("/geofences/"):
            fid = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, json=next(g for g in geofences if g["_id"] == fid))
        if request.url.path == "/commands/poll/rover-1":
            return httpx.Response(500, text="backend unreachable")
        raise AssertionError(request.url.path)

    return handler


def test_command_poll_failure_does_not_raise_and_leaves_state_untouched(tmp_path):
    """A 500 from /commands/poll must be logged and swallowed, per the
    Global Constraints' fault-isolation rule -- not propagate out of
    tick() and kill the unattended process."""
    rover = {"_id": "rover-1", "name": "George", "length_m": 0.6, "turn_style": "spin_in_place"}
    inclusive = {"_id": "fence-1", "type": "inclusive", "boundary": {"type": "Polygon", "coordinates": [FIELD_RING]}}
    client = httpx.Client(transport=httpx.MockTransport(_handler_poll_fails(rover, [inclusive])))
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = MissionRuntime(
        rover_id="rover-1", backend_base_url="http://backend.local",
        local_db_path=str(tmp_path / "test.db"), sensor_hub=hub, esp32_link=FakeEsp32Link(), http_client=client,
    )
    runtime.startup()
    runtime.handle_start_sweep({"geofence_id": "fence-1"})
    hub.script_gps_fix(GpsFix(lat=38.05, lon=-85.0, accuracy_m=2.0, timestamp=0.0))
    runtime.tick()  # seed position_fusion
    runtime._last_command_poll_monotonic = 0.0  # force a poll this tick

    runtime.tick()  # poll_commands raises HTTPStatusError internally -- must not escape

    assert runtime.sweep_session.status == SweepSessionStatus.IN_PROGRESS


def _handler_ack_fails(rover, geofences, commands):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rovers/rover-1":
            return httpx.Response(200, json=rover)
        if request.url.path == "/geofences":
            return httpx.Response(200, json=geofences)
        if request.url.path.startswith("/geofences/"):
            fid = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, json=next(g for g in geofences if g["_id"] == fid))
        if request.url.path == "/commands/poll/rover-1":
            pending, commands[:] = commands[:], []
            return httpx.Response(200, json=pending)
        if request.url.path.startswith("/commands/") and request.url.path.endswith("/ack"):
            return httpx.Response(500, text="ack failed")
        raise AssertionError(request.url.path)

    return handler


def test_ack_failure_does_not_prevent_command_effect_or_raise(tmp_path):
    """A command is handled locally, then acked. If the ack POST fails,
    the local effect (already applied) must stick, and tick() must not
    raise -- the command will simply be re-delivered on a future poll."""
    rover = {"_id": "rover-1", "name": "George", "length_m": 0.6, "turn_style": "spin_in_place"}
    inclusive = {"_id": "fence-1", "type": "inclusive", "boundary": {"type": "Polygon", "coordinates": [FIELD_RING]}}
    commands = [{"_id": "cmd-1", "type": "pause_sweep", "payload": {}}]
    client = httpx.Client(transport=httpx.MockTransport(_handler_ack_fails(rover, [inclusive], commands)))
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = MissionRuntime(
        rover_id="rover-1", backend_base_url="http://backend.local",
        local_db_path=str(tmp_path / "test.db"), sensor_hub=hub, esp32_link=FakeEsp32Link(), http_client=client,
    )
    runtime.startup()
    runtime.handle_start_sweep({"geofence_id": "fence-1"})
    hub.script_gps_fix(GpsFix(lat=38.05, lon=-85.0, accuracy_m=2.0, timestamp=0.0))
    runtime.tick()  # seed position_fusion
    runtime._last_command_poll_monotonic = 0.0  # force a poll this tick

    runtime.tick()  # handles pause_sweep locally, then ack_command 500s -- must not raise

    assert runtime.sweep_session.status == SweepSessionStatus.INTERRUPTED


def test_ota_update_is_refused_while_sweep_session_in_progress(tmp_path):
    commands = [{"_id": "cmd-1", "type": "ota_update", "payload": {"firmware_path": "/firmware/v2.bin"}}]
    acked = []
    runtime = _make_started_runtime(tmp_path, commands, acked)
    assert runtime.sweep_session.status == SweepSessionStatus.IN_PROGRESS
    runtime._last_command_poll_monotonic = 0.0  # force a poll this tick

    runtime.tick()  # must not raise out of the tick itself

    assert runtime.esp32_link.ota_triggers == []  # never actually triggered
    assert acked == []  # never acked, so the backend redelivers it next poll


def test_ota_update_proceeds_with_no_sweep_session(tmp_path):
    commands = [{"_id": "cmd-1", "type": "ota_update", "payload": {"firmware_path": "/firmware/v2.bin"}}]
    acked = []
    runtime = _make_idle_runtime(tmp_path, commands, acked)
    assert runtime.sweep_session is None
    runtime._last_command_poll_monotonic = 0.0

    runtime.tick()

    assert runtime.esp32_link.ota_triggers == ["/firmware/v2.bin"]
    assert acked == ["/commands/cmd-1/ack"]


def test_ota_update_proceeds_when_sweep_session_is_interrupted_not_in_progress(tmp_path):
    """Regression test for the exact correctness gap this plan's design
    found: sweep_session is never reset to None after a pause/stop, so
    gating on mere presence (rather than .status == IN_PROGRESS) would
    block OTA forever after the very first mission ever run.
    """
    commands = [{"_id": "cmd-1", "type": "ota_update", "payload": {"firmware_path": "/firmware/v2.bin"}}]
    acked = []
    runtime = _make_started_runtime(tmp_path, commands, acked)
    runtime.sweep_session.interrupt(datetime.now(timezone.utc))
    assert runtime.sweep_session.status == SweepSessionStatus.INTERRUPTED
    runtime._last_command_poll_monotonic = 0.0

    runtime.tick()

    assert runtime.esp32_link.ota_triggers == ["/firmware/v2.bin"]
    assert acked == ["/commands/cmd-1/ack"]
