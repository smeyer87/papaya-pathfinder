# pathfinder-autonomous/pi-mission/tests/test_hardware_drivers_integration.py
import httpx

from papaya_mission.hardware_esp32_link import HardwareEsp32Link
from papaya_mission.hardware_sensor_hub import (
    HardwareCameraSource,
    HardwareGpsSource,
    HardwareImuSource,
    HardwareSensorHub,
    HardwareUltrasonicSource,
)
from papaya_mission.runtime import MissionRuntime

FIELD_RING = [[-85.10, 38.00], [-85.10, 38.10], [-84.90, 38.10], [-84.90, 38.00], [-85.10, 38.00]]


class _FakeLineSource:
    def readline(self) -> bytes:
        return b""


class _FakeBno055Device:
    euler = (0.0, 0.0, 0.0)
    linear_acceleration = (0.0, 0.0, 0.0)


class _FakePulseMeasurer:
    def measure_echo_pulse_us(self):
        return None


class _FakeClassifierSource:
    def classify(self):
        return None


class _FakeTransport:
    def readline(self) -> bytes:
        return b""

    def write(self, data: bytes) -> None:
        pass


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


def test_assembled_hardware_drivers_satisfy_protocols_and_tick_cleanly(tmp_path):
    sensor_hub = HardwareSensorHub(
        gps=HardwareGpsSource(line_source=_FakeLineSource()),
        imu=HardwareImuSource(device=_FakeBno055Device()),
        ultrasonic=HardwareUltrasonicSource(pulse_measurer=_FakePulseMeasurer()),
        camera=HardwareCameraSource(classifier_source=_FakeClassifierSource()),
    )
    esp32_link = HardwareEsp32Link(transport=_FakeTransport(), port="/dev/fake")

    rover = {"_id": "rover-1", "name": "George", "length_m": 0.6, "turn_style": "spin_in_place"}
    inclusive = {"_id": "fence-1", "type": "inclusive", "boundary": {"type": "Polygon", "coordinates": [FIELD_RING]}}
    client = httpx.Client(transport=httpx.MockTransport(_handler(rover, [inclusive])))

    runtime = MissionRuntime(
        rover_id="rover-1",
        backend_base_url="http://backend.local",
        local_db_path=str(tmp_path / "test.db"),
        sensor_hub=sensor_hub,
        esp32_link=esp32_link,
        http_client=client,
    )
    runtime.startup()
    runtime.handle_start_sweep({"geofence_id": "fence-1"})

    for _ in range(3):
        runtime.tick()  # must not raise; no GPS fix is ever scripted from the fakes

    # Matches the existing, already-tested "never acquired a real fix" behavior
    # (see test_gps_never_acquired_still_triggers_stop_and_alert in
    # test_runtime_tick_sensing.py): the dummy-seed error radius already
    # exceeds GPS_LOSS_MAX_ERROR_RADIUS_M from tick 1, so this is deterministic,
    # not merely one possible outcome among several.
    assert runtime.mission_alert == "gps_stop_and_alert"
