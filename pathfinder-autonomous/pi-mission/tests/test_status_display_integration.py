from datetime import datetime, timezone

import httpx

from papaya_mission.esp32_link import BumpEvent, Esp32Status, FakeEsp32Link
from papaya_mission.position_fusion import GpsFix, ImuReading
from papaya_mission.runtime import MissionRuntime
from papaya_mission.sensor_hub import SimulatedSensorHub
from papaya_mission.status_display import DEFAULT_SCREENS, StatusDisplay

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


class _FakeLcdWriter:
    def __init__(self) -> None:
        self.writes: list[tuple[str, str]] = []

    def write_lines(self, line1: str, line2: str) -> None:
        self.writes.append((line1, line2))


def test_status_display_renders_real_runtime_state_without_raising(tmp_path):
    rover = {"_id": "rover-1", "name": "George", "length_m": 0.6, "turn_style": "spin_in_place"}
    inclusive = {"_id": "fence-1", "type": "inclusive", "boundary": {"type": "Polygon", "coordinates": [FIELD_RING]}}
    client = httpx.Client(transport=httpx.MockTransport(_handler(rover, [inclusive])))
    hub = SimulatedSensorHub(INITIAL_IMU)
    esp32 = FakeEsp32Link()
    runtime = MissionRuntime(
        rover_id="rover-1",
        backend_base_url="http://backend.local",
        local_db_path=str(tmp_path / "test.db"),
        sensor_hub=hub,
        esp32_link=esp32,
        http_client=client,
    )
    runtime.startup()
    runtime.handle_start_sweep({"geofence_id": "fence-1"})
    hub.script_gps_fix(GpsFix(lat=38.05, lon=-85.0, accuracy_m=2.0, timestamp=0.0))
    runtime.tick()  # seeds position_fusion

    esp32.script_bump_events([BumpEvent(detected_at=datetime(2026, 9, 25, tzinfo=timezone.utc))])
    esp32.script_status(Esp32Status(halted_on_contact=True))
    runtime._last_telemetry_sample_monotonic = 0.0  # force a sample this tick
    runtime.tick()

    lcd = _FakeLcdWriter()
    display = StatusDisplay(lcd=lcd)

    screen_names = []
    for _ in range(len(DEFAULT_SCREENS)):
        display.refresh(runtime.last_telemetry_readings)  # must not raise
        screen_names.append(display.current_screen.name)
        display.next_screen()

    assert screen_names == ["position", "mission", "obstacles", "drive"]
    assert len(lcd.writes) == 4

    position_line1, _position_line2 = lcd.writes[0]
    assert position_line1 == "38.0500,-85.0000"  # exact: guards against truncation regressions

    obstacles_line1, obstacles_line2 = lcd.writes[2]
    assert obstacles_line1 == "Obstacles: 1"
    assert obstacles_line2 == "Last: unknown"  # obstacle_from_bump_contact's type

    _drive_line1, drive_line2 = lcd.writes[3]
    assert drive_line2 == "HALTED"


def test_status_display_shows_link_unknown_when_esp32_status_read_fails(tmp_path):
    rover = {"_id": "rover-1", "name": "George", "length_m": 0.6, "turn_style": "spin_in_place"}
    inclusive = {"_id": "fence-1", "type": "inclusive", "boundary": {"type": "Polygon", "coordinates": [FIELD_RING]}}
    client = httpx.Client(transport=httpx.MockTransport(_handler(rover, [inclusive])))
    hub = SimulatedSensorHub(INITIAL_IMU)
    esp32 = FakeEsp32Link()
    runtime = MissionRuntime(
        rover_id="rover-1",
        backend_base_url="http://backend.local",
        local_db_path=str(tmp_path / "test.db"),
        sensor_hub=hub,
        esp32_link=esp32,
        http_client=client,
    )
    runtime.startup()
    runtime.handle_start_sweep({"geofence_id": "fence-1"})
    hub.script_gps_fix(GpsFix(lat=38.05, lon=-85.0, accuracy_m=2.0, timestamp=0.0))
    runtime.tick()  # seeds position_fusion

    def _boom():
        raise RuntimeError("esp32 link dropped")

    # A dropped Pi<->ESP32 link fails both calls together, since both
    # status() and read_drive_status() drain the same serial transport.
    runtime.esp32_link.status = _boom
    runtime.esp32_link.read_drive_status = _boom
    runtime._last_telemetry_sample_monotonic = 0.0  # force a sample this tick
    runtime.tick()  # must not raise

    lcd = _FakeLcdWriter()
    display = StatusDisplay(lcd=lcd)
    for _ in range(3):  # cycle position -> mission -> obstacles -> drive
        display.next_screen()
    display.refresh(runtime.last_telemetry_readings)

    drive_line1, drive_line2 = lcd.writes[0]
    assert drive_line1 == "Throttle: ?"
    assert drive_line2 == "LINK?"
