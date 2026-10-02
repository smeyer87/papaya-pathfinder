# pathfinder-autonomous/pi-mission/tests/test_digital_twin_scenarios.py
import httpx

from papaya_mission import local_store
from papaya_mission.digital_twin import TwinObstacle, TwinWorld
from papaya_mission.geo_utils import project_position
from papaya_mission.runtime import MissionRuntime

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
        if request.url.path == "/commands/poll/rover-1":
            # This test doesn't exercise command polling -- it just needs the
            # poll to not crash if MissionRuntime's 1-second cadence
            # (COMMAND_POLL_INTERVAL_S) happens to fire mid-test under
            # full-suite system load, even though this test is fast in
            # isolation. An empty list is exactly what a real backend
            # returns when nothing is queued.
            return httpx.Response(200, json=[])
        raise AssertionError(request.url.path)

    return handler


def _make_started_runtime(tmp_path, world: TwinWorld) -> MissionRuntime:
    rover = {"_id": "rover-1", "name": "George", "length_m": 0.6, "turn_style": "spin_in_place"}
    inclusive = {"_id": "fence-1", "type": "inclusive", "boundary": {"type": "Polygon", "coordinates": [FIELD_RING]}}
    client = httpx.Client(transport=httpx.MockTransport(_handler(rover, [inclusive])))
    runtime = MissionRuntime(
        rover_id="rover-1",
        backend_base_url="http://backend.local",
        local_db_path=str(tmp_path / "test.db"),
        sensor_hub=world.sensor_hub,
        esp32_link=world.esp32_link,
        http_client=client,
    )
    runtime.startup()
    runtime.handle_start_sweep({"geofence_id": "fence-1"})
    return runtime


def test_ultrasonic_and_camera_agree_on_same_forward_obstacle(tmp_path):
    world = TwinWorld(start_lat=38.05, start_lon=-85.0)
    obstacle_lat, obstacle_lon = project_position(38.05, -85.0, bearing_deg=0.0, distance_m=3.0)
    world.obstacles.append(TwinObstacle(
        lat=obstacle_lat, lon=obstacle_lon, collision_radius_m=0.3,
        classified_type="barrel", classification_confidence=0.9,
    ))
    runtime = _make_started_runtime(tmp_path, world)

    world.point_mast_at(world.mast_sweep_limit_deg)  # look away for the seed tick
    runtime.tick()  # seeds position_fusion from the twin's GPS fix, no detection yet

    world.point_mast_at(0.0)  # now look straight at the obstacle
    runtime.tick()

    saved = local_store.list_unsynced_obstacles(runtime.conn)
    assert len(saved) == 1
    assert saved[0]["type"] == "barrel"
    assert saved[0]["status"] == "permanent-pending"
    assert saved[0]["detection_method"] == "ultrasonic+camera"


def test_bump_contact_halts_movement_and_is_recorded(tmp_path):
    world = TwinWorld(start_lat=38.05, start_lon=-85.0)
    world.point_mast_at(world.mast_sweep_limit_deg)  # keep the sweep away from the obstacle throughout
    obstacle_lat, obstacle_lon = project_position(38.05, -85.0, bearing_deg=0.0, distance_m=1.0)
    world.obstacles.append(TwinObstacle(
        lat=obstacle_lat, lon=obstacle_lon, collision_radius_m=0.5,
        classified_type="unknown", classification_confidence=0.0,
    ))
    runtime = _make_started_runtime(tmp_path, world)
    runtime.tick()  # seeds position_fusion; mast is pointed away, so no ultrasonic pairing yet

    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=1.0)  # drives 1m north, straight into the obstacle
    assert world._halted_on_contact is True

    position_before_next_step = (world.lat, world.lon)
    runtime.tick()  # polls the bump event, saves a contact-only obstacle

    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=1.0)  # halted -- should not move further
    assert (world.lat, world.lon) == position_before_next_step

    saved = local_store.list_unsynced_obstacles(runtime.conn)
    assert len(saved) == 1
    assert saved[0]["detection_method"] == "contact-only"
    assert saved[0]["status"] == "permanent-pending"


def test_gps_unavailable_triggers_stop_and_alert(tmp_path):
    world = TwinWorld(start_lat=38.05, start_lon=-85.0)
    runtime = _make_started_runtime(tmp_path, world)
    runtime.tick()  # seeds position_fusion from a real fix

    world.gps_available = False
    runtime._last_gps_fix_monotonic -= 31.0  # simulate 31s of GPS silence, past the 30s grace period
    runtime.tick()

    assert runtime.mission_alert == "gps_stop_and_alert"
