from datetime import datetime, timezone

import httpx

from papaya_mission.esp32_link import Esp32Status, FakeEsp32Link
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
    runtime.tick()  # seed position_fusion
    return runtime


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
