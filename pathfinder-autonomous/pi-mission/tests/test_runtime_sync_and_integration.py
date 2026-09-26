import httpx

from papaya_mission.esp32_link import FakeEsp32Link
from papaya_mission.position_fusion import GpsFix, ImuReading
from papaya_mission.runtime import MissionRuntime
from papaya_mission.sensor_hub import ObstacleDetection, SimulatedSensorHub
from papaya_mission.sweep_session import SweepSessionStatus

INITIAL_IMU = ImuReading(heading_deg=0.0, forward_acceleration_mps2=0.0, timestamp=0.0)
FIELD_RING = [[-85.001, 38.000], [-85.001, 38.002], [-84.999, 38.002], [-84.999, 38.000], [-85.001, 38.000]]


def _handler(rover, geofences, commands, sync_calls):
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
            return httpx.Response(200, json={"status": "acked"})
        if request.url.path.startswith("/sync/"):
            sync_calls.append(request.url.path)
            return httpx.Response(200, json={"received": 1, "inserted": 1})
        raise AssertionError(request.url.path)

    return handler


def test_stop_sweep_triggers_home_return_sync(tmp_path):
    rover = {"_id": "rover-1", "name": "George", "length_m": 0.6, "turn_style": "spin_in_place"}
    inclusive = {"_id": "fence-1", "type": "inclusive", "boundary": {"type": "Polygon", "coordinates": [FIELD_RING]}}
    commands = [{"_id": "cmd-1", "type": "stop_sweep", "payload": {}}]
    sync_calls = []
    client = httpx.Client(transport=httpx.MockTransport(_handler(rover, [inclusive], commands, sync_calls)))
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = MissionRuntime(
        rover_id="rover-1", backend_base_url="http://backend.local",
        local_db_path=str(tmp_path / "test.db"), sensor_hub=hub, esp32_link=FakeEsp32Link(), http_client=client,
    )
    runtime.startup()
    runtime.handle_start_sweep({"geofence_id": "fence-1"})
    hub.script_gps_fix(GpsFix(lat=38.001, lon=-85.0, accuracy_m=1.0, timestamp=0.0))
    # sync_client's sync_obstacles/sync_telemetry (Pi Local Store & Sync
    # Client plan) each skip their POST when nothing is unsynced -- so
    # proving the Home-return sync fires across all three entity types
    # requires at least one obstacle and one telemetry sample to actually
    # exist first. Script an ultrasonic+camera detection so this same tick
    # records an obstacle, and force the telemetry-sample cadence (the
    # same "reset the monotonic sentinel" trick already used below for the
    # command-poll cadence) so it samples one telemetry record too.
    hub.script_ultrasonic(ObstacleDetection(relative_bearing_deg=0.0, range_m=2.0))
    hub.script_camera(("barrel", 0.9))
    runtime._last_telemetry_sample_monotonic = 0.0
    runtime.tick()  # seed position, detect an obstacle, sample telemetry
    runtime._last_command_poll_monotonic = 0.0

    runtime.tick()  # polls and handles stop_sweep -> triggers sync

    assert runtime.sweep_session.status == SweepSessionStatus.INTERRUPTED
    assert "/sync/sweep-sessions" in sync_calls
    assert "/sync/obstacles" in sync_calls
    assert "/sync/telemetry" in sync_calls


def test_full_mission_lifecycle_end_to_end(tmp_path):
    """start_sweep -> a few ticks -> stop_sweep -> sync, proving the
    wiring end to end (mirrors every other Pi-mission plan's Task 6)."""
    rover = {"_id": "rover-1", "name": "George", "length_m": 0.6, "turn_style": "spin_in_place"}
    inclusive = {"_id": "fence-1", "type": "inclusive", "boundary": {"type": "Polygon", "coordinates": [FIELD_RING]}}
    commands: list = []
    sync_calls: list = []
    client = httpx.Client(transport=httpx.MockTransport(_handler(rover, [inclusive], commands, sync_calls)))
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = MissionRuntime(
        rover_id="rover-1", backend_base_url="http://backend.local",
        local_db_path=str(tmp_path / "test.db"), sensor_hub=hub, esp32_link=FakeEsp32Link(), http_client=client,
    )

    runtime.startup()
    assert runtime.sweep_session is None

    runtime.handle_start_sweep({"geofence_id": "fence-1"})
    assert runtime.sweep_session is not None

    hub.script_gps_fix(GpsFix(lat=38.001, lon=-85.0, accuracy_m=1.0, timestamp=0.0))
    for _ in range(3):
        runtime.tick()

    commands.append({"_id": "cmd-1", "type": "stop_sweep", "payload": {}})
    runtime._last_command_poll_monotonic = 0.0
    runtime.tick()

    assert runtime.sweep_session.status == SweepSessionStatus.INTERRUPTED
    assert sync_calls.count("/sync/sweep-sessions") == 1


def _handler_sync_fails(rover, geofences, commands):
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
            return httpx.Response(200, json={"status": "acked"})
        if request.url.path.startswith("/sync/"):
            return httpx.Response(500, text="backend unreachable")
        raise AssertionError(request.url.path)

    return handler


def test_home_return_sync_failure_does_not_raise_and_session_still_interrupted(tmp_path):
    """The local interrupt (from stop_sweep) and the Home-return sync
    attempt are independent: a failed sync must not raise out of tick(),
    and must not undo the local state change -- the records simply stay
    unsynced for a later attempt."""
    rover = {"_id": "rover-1", "name": "George", "length_m": 0.6, "turn_style": "spin_in_place"}
    inclusive = {"_id": "fence-1", "type": "inclusive", "boundary": {"type": "Polygon", "coordinates": [FIELD_RING]}}
    commands = [{"_id": "cmd-1", "type": "stop_sweep", "payload": {}}]
    client = httpx.Client(transport=httpx.MockTransport(_handler_sync_fails(rover, [inclusive], commands)))
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = MissionRuntime(
        rover_id="rover-1", backend_base_url="http://backend.local",
        local_db_path=str(tmp_path / "test.db"), sensor_hub=hub, esp32_link=FakeEsp32Link(), http_client=client,
    )
    runtime.startup()
    runtime.handle_start_sweep({"geofence_id": "fence-1"})
    hub.script_gps_fix(GpsFix(lat=38.001, lon=-85.0, accuracy_m=1.0, timestamp=0.0))
    runtime.tick()  # seed position
    runtime._last_command_poll_monotonic = 0.0

    runtime.tick()  # polls and handles stop_sweep -> sync_all 500s internally -- must not raise

    assert runtime.sweep_session.status == SweepSessionStatus.INTERRUPTED
