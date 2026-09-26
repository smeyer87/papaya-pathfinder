import httpx
import pytest

from papaya_mission.esp32_link import FakeEsp32Link
from papaya_mission.position_fusion import ImuReading
from papaya_mission.runtime import MissionRuntime
from papaya_mission.sensor_hub import SimulatedSensorHub
from papaya_mission.sweep_session import SweepSessionStatus

INITIAL_IMU = ImuReading(heading_deg=0.0, forward_acceleration_mps2=0.0, timestamp=0.0)

FIELD_RING = [
    [-85.10, 38.00], [-85.10, 38.10], [-84.90, 38.10], [-84.90, 38.00], [-85.10, 38.00],
]


def _handler_for(rover: dict, geofences: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rovers/rover-1":
            return httpx.Response(200, json=rover)
        if request.url.path == "/geofences/fence-1":
            return httpx.Response(200, json=geofences[0])
        if request.url.path == "/geofences":
            return httpx.Response(200, json=geofences)
        raise AssertionError(f"unexpected request: {request.url.path}")

    return handler


def _make_runtime(tmp_path, rover: dict, geofences: list[dict]) -> MissionRuntime:
    client = httpx.Client(transport=httpx.MockTransport(_handler_for(rover, geofences)))
    return MissionRuntime(
        rover_id="rover-1",
        backend_base_url="http://backend.local",
        local_db_path=str(tmp_path / "test.db"),
        sensor_hub=SimulatedSensorHub(INITIAL_IMU),
        esp32_link=FakeEsp32Link(),
        http_client=client,
    )


def test_startup_fetches_rover_and_builds_expected_metrics(tmp_path):
    rover = {
        "_id": "rover-1",
        "name": "George",
        "turn_style": "spin_in_place",
        "sensor_manifest": [
            {"sensor": "gps", "installed": True},
            {"sensor": "imu", "installed": True},
            {"sensor": "bump", "installed": False},
        ],
    }
    runtime = _make_runtime(tmp_path, rover, geofences=[])

    runtime.startup()

    assert runtime.rover["_id"] == "rover-1"
    assert runtime.expected_metrics == {"gps", "imu"}
    assert runtime.sweep_session is None  # nothing in local storage yet


def test_start_sweep_builds_and_persists_sweep_session(tmp_path):
    rover = {"_id": "rover-1", "name": "George", "turn_style": "spin_in_place"}
    inclusive = {"_id": "fence-1", "type": "inclusive", "boundary": {"type": "Polygon", "coordinates": [FIELD_RING]}}
    runtime = _make_runtime(tmp_path, rover, geofences=[inclusive])
    runtime.startup()

    runtime.handle_start_sweep({"geofence_id": "fence-1"})

    assert runtime.sweep_session is not None
    assert runtime.sweep_session.rover_id == "rover-1"
    assert runtime.sweep_session.geofence_id == "fence-1"
    assert runtime.sweep_session.status == SweepSessionStatus.IN_PROGRESS
    assert len(runtime.sweep_session.pattern) > 0
    assert runtime.exclusion_polygons == []

    from papaya_mission import local_store
    saved = local_store.list_unsynced_sweep_sessions(runtime.conn)
    assert len(saved) == 1
    assert saved[0]["id"] == runtime.sweep_session.id


def test_start_sweep_excludes_exclusive_geofences_from_inclusive_list(tmp_path):
    rover = {"_id": "rover-1", "name": "George", "turn_style": "spin_in_place"}
    inclusive = {"_id": "fence-1", "type": "inclusive", "boundary": {"type": "Polygon", "coordinates": [FIELD_RING]}}
    pond_ring = [[-85.05, 38.04], [-85.05, 38.06], [-85.03, 38.06], [-85.03, 38.04], [-85.05, 38.04]]
    exclusive = {"_id": "fence-2", "type": "exclusive", "boundary": {"type": "Polygon", "coordinates": [pond_ring]}}
    runtime = _make_runtime(tmp_path, rover, geofences=[inclusive, exclusive])
    runtime.startup()

    runtime.handle_start_sweep({"geofence_id": "fence-1"})

    assert len(runtime.exclusion_polygons) == 1
