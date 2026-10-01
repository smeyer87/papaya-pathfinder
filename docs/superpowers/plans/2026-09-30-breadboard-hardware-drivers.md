# Breadboard Hardware Drivers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build real, Protocol-conforming `SensorHub`/`Esp32Link` driver implementations (`hardware_sensor_hub.py`, `hardware_esp32_link.py`) and the LCD status display (`status_display.py`) for the breadboard bench rig, so the existing, already-tested `MissionRuntime` can run against real hardware the same way it already runs against `SimulatedSensorHub`/the digital twin.

**Architecture:** Every hardware-touching object (a serial port, an I2C device, a GPIO pulse timer, an LCD's byte-banged write sequence, a camera classifier, an `esptool` invocation) is injected into these classes via the constructor, typed against a small `Protocol` defined locally in the same file — never imported as a concrete hardware library. That keeps 100% of the logic in this plan (message framing, state caching, NMEA parsing, screen content, button dispatch) fully unit-testable with in-memory fakes, with zero dependency on real hardware or hardware-specific Python packages (`pyserial`, `pigpio`, `adafruit-blinka`, `picamera2`) being installed or importable in this environment.

**Tech Stack:** Python 3.12, pytest — no new dependencies. Reuses the existing `GpsFix`/`ImuReading` (`position_fusion.py`), `ObstacleDetection` (`sensor_hub.py`), `BumpEvent`/`DriveStatus`/`Esp32Status` (`esp32_link.py`) types unchanged.

## Global Constraints

- Additive only: `sensor_hub.py`, `esp32_link.py`, and `runtime.py` are untouched. This plan adds three new files and their tests.
- **No hardware-specific imports anywhere in these files.** `pigpio`, `pyserial` (`serial`), `adafruit-blinka`/`adafruit-circuitpython-bno055`, and `picamera2` must never appear as top-level (or any) imports in `hardware_sensor_hub.py`, `hardware_esp32_link.py`, or `status_display.py`. Every hardware dependency is received via constructor injection, typed against a `Protocol` defined in the same file. `pathfinder-autonomous/pi-mission/requirements.txt` is **not** modified by this plan.
- **Constructing real hardware objects is out of scope for this plan** — a real `serial.Serial`, a real `pigpio.pi()` connection, a real Adafruit BNO055 device, a real picamera2/IMX500 classifier, and a real `esptool.py` invocation are all bench-time work, done once at the workbench with real hardware and current library docs in hand — consistent with the same decision already made for the ESP32 firmware itself.
- The bench rig has no mast-rotation servo wired (not part of `docs/wiring/breadboard-wiring-layout.yaml`) — the ultrasonic sensor is simply forward-facing. `ObstacleDetection.relative_bearing_deg` is always `0.0` in this plan's ultrasonic driver.
- GPS accuracy is derived from the GGA sentence's HDOP field via a documented heuristic (`accuracy_m = hdop * 5.0`, a typical SBAS-corrected user-equivalent-range-error estimate) — an approximation to refine once real bench fix data exists, not a precise spec.
- IMU forward-acceleration axis choice (which of the BNO055's three linear-acceleration axes is "forward") assumes a specific physical mounting orientation and is flagged in code for confirmation once physically mounted.
- The camera driver is a thin Protocol-conformance wrapper only — the real Pi AI Camera / picamera2 / IMX500 classification backend is explicitly deferred to bench time (its API is fast-moving and best confirmed against the actual camera and current docs, not guessed at here).
- Design spec: `docs/superpowers/specs/2026-09-30-breadboard-bench-rig-design.md`.

---

## File Structure

```
pathfinder-autonomous/pi-mission/
  papaya_mission/
    hardware_esp32_link.py   # NEW -- HardwareEsp32Link: real Esp32Link over
                              #        an injected transport (serial-like)
    hardware_sensor_hub.py   # NEW -- HardwareGpsSource, HardwareImuSource,
                              #        HardwareUltrasonicSource,
                              #        HardwareCameraSource, HardwareSensorHub
    status_display.py        # NEW -- StatusDisplay, Screen, DEFAULT_SCREENS
  tests/
    test_hardware_esp32_link.py        # NEW
    test_hardware_sensor_hub.py        # NEW
    test_status_display.py             # NEW
    test_hardware_drivers_integration.py  # NEW -- end-to-end against MissionRuntime
```

---

### Task 1: Hardware Esp32Link driver

**Files:**
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/hardware_esp32_link.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_hardware_esp32_link.py`

**Interfaces:**
- Consumes: `papaya_mission.esp32_link.{BumpEvent, DriveStatus, Esp32Status}` (unchanged).
- Produces: `HardwareTransport` (`Protocol`: `readline() -> bytes`, `write(data: bytes) -> None`), `FlashRunner` (`Protocol`: `__call__(port: str, firmware_path: str) -> bool`), `HardwareEsp32Link(transport: HardwareTransport, port: str, flash_runner: FlashRunner = ...)` implementing `poll_bump_events`, `status`, `read_drive_status`, `send_geofence_update`, `trigger_ota` per the existing `Esp32Link` Protocol. Task 5 passes an instance of this straight to `MissionRuntime(esp32_link=...)`.

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_hardware_esp32_link.py
import json

from papaya_mission.hardware_esp32_link import HardwareEsp32Link


class _FakeTransport:
    def __init__(self, lines: list[bytes] | None = None):
        self._lines = list(lines or [])
        self.written: list[bytes] = []

    def readline(self) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        return b""

    def write(self, data: bytes) -> None:
        self.written.append(data)


def _line(message: dict) -> bytes:
    return (json.dumps(message) + "\n").encode("utf-8")


def test_poll_bump_events_returns_empty_when_nothing_arrived():
    link = HardwareEsp32Link(transport=_FakeTransport(), port="/dev/fake")

    assert link.poll_bump_events() == []


def test_poll_bump_events_drains_bump_lines_and_consumes_once():
    transport = _FakeTransport([_line({"type": "bump"}), _line({"type": "bump"})])
    link = HardwareEsp32Link(transport=transport, port="/dev/fake")

    events = link.poll_bump_events()
    assert len(events) == 2
    assert link.poll_bump_events() == []


def test_status_reflects_latest_heartbeat_halted_flag():
    transport = _FakeTransport([
        _line({"type": "status", "halted": False, "throttle": 0.0}),
        _line({"type": "status", "halted": True, "throttle": 0.3}),
    ])
    link = HardwareEsp32Link(transport=transport, port="/dev/fake")

    assert link.status().halted_on_contact is True


def test_read_drive_status_reflects_latest_heartbeat_throttle():
    transport = _FakeTransport([_line({"type": "status", "halted": False, "throttle": 0.42})])
    link = HardwareEsp32Link(transport=transport, port="/dev/fake")

    status = link.read_drive_status()
    assert status.servo_positions_deg == {}
    assert status.throttle_position == 0.42


def test_malformed_line_is_skipped_without_raising():
    transport = _FakeTransport([b"not json at all\n", _line({"type": "bump"})])
    link = HardwareEsp32Link(transport=transport, port="/dev/fake")

    events = link.poll_bump_events()
    assert len(events) == 1


def test_unknown_message_type_is_ignored():
    transport = _FakeTransport([_line({"type": "something_unexpected"})])
    link = HardwareEsp32Link(transport=transport, port="/dev/fake")

    assert link.status().halted_on_contact is False
    assert link.poll_bump_events() == []


def test_send_geofence_update_writes_json_line_and_records_call():
    transport = _FakeTransport()
    link = HardwareEsp32Link(transport=transport, port="/dev/fake")

    link.send_geofence_update(["zone-1", "zone-2"])

    assert link.geofence_updates_sent == [["zone-1", "zone-2"]]
    written = json.loads(transport.written[0].decode("utf-8").strip())
    assert written == {"type": "geofence_update", "zone_ids": ["zone-1", "zone-2"]}


def test_trigger_ota_invokes_flash_runner_with_port_and_path_and_records_call():
    calls = []

    def fake_flash_runner(port: str, firmware_path: str) -> bool:
        calls.append((port, firmware_path))
        return True

    link = HardwareEsp32Link(transport=_FakeTransport(), port="/dev/fake", flash_runner=fake_flash_runner)

    link.trigger_ota("/firmware/v2.bin")

    assert link.ota_triggers == ["/firmware/v2.bin"]
    assert calls == [("/dev/fake", "/firmware/v2.bin")]


def test_trigger_ota_logs_error_when_flash_runner_fails(caplog):
    link = HardwareEsp32Link(
        transport=_FakeTransport(), port="/dev/fake", flash_runner=lambda port, path: False
    )

    with caplog.at_level("ERROR"):
        link.trigger_ota("/firmware/v2.bin")

    assert any("flash failed" in record.message for record in caplog.records)
```

- [ ] **Step 2: Run the tests and verify they fail**

Run (from `pathfinder-autonomous/pi-mission/`): `pytest tests/test_hardware_esp32_link.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'papaya_mission.hardware_esp32_link'`

- [ ] **Step 3: Write the implementation**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/hardware_esp32_link.py
"""Real Esp32Link implementation over the Pi<->ESP32 UART link -- see
design spec: docs/superpowers/specs/2026-09-30-breadboard-bench-rig-design.md.

Message framing is newline-delimited JSON. The ESP32 pushes a heartbeat
(halted flag + throttle) roughly every 150ms plus an eager bump message
the instant one occurs -- this driver never blocks waiting for a reply,
it just drains whatever has arrived on the transport each time a
Protocol method is called and serves the request from cached state.

The transport and flash-runner are both injected via the constructor so
every line of protocol logic here is testable without a real serial port
or a real ESP32. Constructing the real pyserial-backed transport, and
invoking a real esptool.py flash against real hardware, are bench-time
work -- not built here.
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from papaya_mission.esp32_link import BumpEvent, DriveStatus, Esp32Status

logger = logging.getLogger("papaya_mission.hardware_esp32_link")


class HardwareTransport(Protocol):
    """Duck-typed shape of the Pi<->ESP32 serial link this driver needs.
    `readline()` must return b"" (not block) when nothing new has
    arrived yet -- matching pyserial's own non-blocking-timeout mode,
    not its default blocking behavior.
    """

    def readline(self) -> bytes: ...
    def write(self, data: bytes) -> None: ...


class FlashRunner(Protocol):
    """Invokes esptool.py against the given port with the given firmware
    file, returning True on success.
    """

    def __call__(self, port: str, firmware_path: str) -> bool: ...


def _default_flash_runner(port: str, firmware_path: str) -> bool:
    result = subprocess.run(
        ["esptool.py", "--port", port, "write_flash", "0x10000", firmware_path],
        capture_output=True,
    )
    return result.returncode == 0


@dataclass
class HardwareEsp32Link:
    """Real Esp32Link implementation. This driver does not own exclusive
    access to `port` itself (the caller's transport does) -- trigger_ota()
    expects the caller to release/close the transport's hold on the port
    before calling it, and reopen it afterward, since esptool needs the
    port free. See the design spec's OTA section for the full mechanism.
    """

    transport: HardwareTransport
    port: str
    flash_runner: FlashRunner = _default_flash_runner
    _pending_bump_events: list[BumpEvent] = field(default_factory=list)
    _halted_on_contact: bool = False
    _last_throttle: float = 0.0
    geofence_updates_sent: list[list[str]] = field(default_factory=list)
    ota_triggers: list[str] = field(default_factory=list)

    def _drain_transport(self) -> None:
        while True:
            line = self.transport.readline()
            if not line:
                break
            self._handle_line(line)

    def _handle_line(self, line: bytes) -> None:
        try:
            message = json.loads(line.decode("utf-8").strip())
        except (ValueError, UnicodeDecodeError):
            logger.warning("Malformed line from ESP32: %r", line, exc_info=True)
            return
        message_type = message.get("type")
        if message_type == "bump":
            self._pending_bump_events.append(BumpEvent(detected_at=datetime.now(timezone.utc)))
        elif message_type == "status":
            self._halted_on_contact = bool(message.get("halted", False))
            self._last_throttle = float(message.get("throttle", 0.0))
        else:
            logger.warning("Unknown message type from ESP32: %r", message_type)

    def poll_bump_events(self) -> list[BumpEvent]:
        self._drain_transport()
        events, self._pending_bump_events = self._pending_bump_events, []
        return events

    def status(self) -> Esp32Status:
        self._drain_transport()
        return Esp32Status(halted_on_contact=self._halted_on_contact)

    def read_drive_status(self) -> DriveStatus:
        self._drain_transport()
        return DriveStatus(servo_positions_deg={}, throttle_position=self._last_throttle)

    def send_geofence_update(self, exclusion_zone_ids: list[str]) -> None:
        self.geofence_updates_sent.append(exclusion_zone_ids)
        line = json.dumps({"type": "geofence_update", "zone_ids": exclusion_zone_ids}) + "\n"
        self.transport.write(line.encode("utf-8"))

    def trigger_ota(self, firmware_path: str) -> None:
        self.ota_triggers.append(firmware_path)
        success = self.flash_runner(self.port, firmware_path)
        if not success:
            logger.error("esptool flash failed for %s on %s", firmware_path, self.port)
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_hardware_esp32_link.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/hardware_esp32_link.py pathfinder-autonomous/pi-mission/tests/test_hardware_esp32_link.py
git commit -m "feat(pi-mission): add hardware Esp32Link driver over injected UART transport"
```

---

### Task 2: GPS + IMU hardware sensor sources

**Files:**
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/hardware_sensor_hub.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_hardware_sensor_hub.py`

**Interfaces:**
- Consumes: `papaya_mission.position_fusion.{GpsFix, ImuReading}` (unchanged).
- Produces: `GpsLineSource` (`Protocol`: `readline() -> bytes`), `HardwareGpsSource(line_source: GpsLineSource, clock: Callable[[], float] = time.monotonic)` implementing `GpsSource`; `Bno055Device` (`Protocol`: `.euler -> tuple[float|None, float|None, float|None]`, `.linear_acceleration -> tuple[float|None, float|None, float|None]`), `HardwareImuSource(device: Bno055Device, clock: Callable[[], float] = time.monotonic)` implementing `ImuSource`. Task 3 adds `HardwareUltrasonicSource`/`HardwareCameraSource`/`HardwareSensorHub` to this same file.

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_hardware_sensor_hub.py
import math

from papaya_mission.hardware_sensor_hub import HardwareGpsSource, HardwareImuSource

# A real GGA sentence: fix quality 1, HDOP 1.2, lat 38 29.3754' N, lon 85 45.1234' W
_GGA_FIX = b"$GPGGA,123519,3829.3754,N,08545.1234,W,1,08,1.2,10.0,M,-34.2,M,,*6A\n"
_GGA_NO_FIX = b"$GPGGA,123519,,,,,0,00,99.9,,,,,,,*66\n"


def test_gps_returns_none_with_no_lines_available():
    source = HardwareGpsSource(line_source=_FakeLineSource([]), clock=lambda: 1.0)

    assert source.read() is None


def test_gps_parses_a_valid_gga_fix():
    source = HardwareGpsSource(line_source=_FakeLineSource([_GGA_FIX]), clock=lambda: 1.0)

    fix = source.read()

    assert fix is not None
    assert math.isclose(fix.lat, 38.0 + 29.3754 / 60.0, abs_tol=1e-6)
    assert math.isclose(fix.lon, -(85.0 + 45.1234 / 60.0), abs_tol=1e-6)
    assert math.isclose(fix.accuracy_m, 1.2 * 5.0, rel_tol=1e-6)
    assert fix.timestamp == 1.0


def test_gps_ignores_a_no_fix_sentence():
    source = HardwareGpsSource(line_source=_FakeLineSource([_GGA_NO_FIX]), clock=lambda: 1.0)

    assert source.read() is None


def test_gps_keeps_the_freshest_fix_when_multiple_lines_arrived():
    second_fix = b"$GPGGA,123520,3830.0000,N,08545.1234,W,1,08,1.0,10.0,M,-34.2,M,,*6B\n"
    source = HardwareGpsSource(line_source=_FakeLineSource([_GGA_FIX, second_fix]), clock=lambda: 2.0)

    fix = source.read()

    assert math.isclose(fix.lat, 38.0 + 30.0000 / 60.0, abs_tol=1e-6)


def test_gps_ignores_malformed_lines():
    source = HardwareGpsSource(line_source=_FakeLineSource([b"garbage\n", _GGA_FIX]), clock=lambda: 1.0)

    assert source.read() is not None


class _FakeLineSource:
    def __init__(self, lines: list[bytes]):
        self._lines = list(lines)

    def readline(self) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        return b""


class _FakeBno055Device:
    def __init__(self, euler=(None, None, None), linear_acceleration=(None, None, None)):
        self.euler = euler
        self.linear_acceleration = linear_acceleration


def test_imu_returns_default_reading_before_any_valid_read():
    source = HardwareImuSource(device=_FakeBno055Device(), clock=lambda: 1.0)

    reading = source.read()

    assert reading.heading_deg == 0.0
    assert reading.forward_acceleration_mps2 == 0.0


def test_imu_reads_heading_and_forward_acceleration():
    device = _FakeBno055Device(euler=(90.0, 1.0, 2.0), linear_acceleration=(0.1, 0.5, -9.8))
    source = HardwareImuSource(device=device, clock=lambda: 3.0)

    reading = source.read()

    assert reading.heading_deg == 90.0
    assert reading.forward_acceleration_mps2 == 0.5
    assert reading.timestamp == 3.0


def test_imu_returns_last_known_reading_when_device_reports_none():
    device = _FakeBno055Device(euler=(45.0, 0.0, 0.0), linear_acceleration=(0.0, 1.0, 0.0))
    source = HardwareImuSource(device=device, clock=lambda: 1.0)
    first = source.read()

    device.euler = (None, None, None)
    device.linear_acceleration = (None, None, None)
    second = source.read()

    assert second == first
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_hardware_sensor_hub.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'papaya_mission.hardware_sensor_hub'`

- [ ] **Step 3: Write the implementation**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/hardware_sensor_hub.py
"""Real SensorHub implementations for the breadboard bench rig -- see
design spec: docs/superpowers/specs/2026-09-30-breadboard-bench-rig-design.md.

Every hardware dependency (a serial-like line source, an I2C IMU device,
a GPIO pulse timer, a camera classifier) is injected via the
constructor and typed against a Protocol defined in this file, never a
real hardware library -- see each class's docstring. Constructing the
real hardware objects (pyserial, pigpio, adafruit-blinka/BNO055,
picamera2/IMX500) is bench-time work, not built here.
"""
from __future__ import annotations

import time
from typing import Callable, Protocol

from papaya_mission.position_fusion import GpsFix, ImuReading


class GpsLineSource(Protocol):
    """Duck-typed shape of the GPS's serial link. readline() must return
    b"" (not block) when nothing new has arrived -- same convention as
    HardwareEsp32Link's transport.
    """

    def readline(self) -> bytes: ...


def _nmea_coord_to_decimal(value: str, hemisphere: str) -> float | None:
    if not value:
        return None
    dot = value.index(".")
    degrees = int(value[: dot - 2])
    minutes = float(value[dot - 2 :])
    decimal = degrees + minutes / 60.0
    if hemisphere in ("S", "W"):
        decimal = -decimal
    return decimal


def _parse_gga(line: str, timestamp: float) -> GpsFix | None:
    if "GGA" not in line:
        return None
    body = line.split("*")[0]
    fields = body.split(",")
    if len(fields) < 9:
        return None
    try:
        fix_quality = int(fields[6]) if fields[6] else 0
        if fix_quality == 0:
            return None
        lat = _nmea_coord_to_decimal(fields[2], fields[3])
        lon = _nmea_coord_to_decimal(fields[4], fields[5])
        hdop = float(fields[8]) if fields[8] else 99.0
    except (ValueError, IndexError):
        return None
    if lat is None or lon is None:
        return None
    # Rough accuracy estimate: HDOP * typical SBAS-corrected UERE (~5m).
    # Refine once real-world fix data is available from bench testing.
    accuracy_m = hdop * 5.0
    return GpsFix(lat=lat, lon=lon, accuracy_m=accuracy_m, timestamp=timestamp)


class HardwareGpsSource:
    def __init__(self, line_source: GpsLineSource, clock: Callable[[], float] = time.monotonic) -> None:
        self._line_source = line_source
        self._clock = clock

    def read(self) -> GpsFix | None:
        fix: GpsFix | None = None
        while True:
            raw = self._line_source.readline()
            if not raw:
                break
            try:
                line = raw.decode("ascii", errors="ignore").strip()
            except UnicodeDecodeError:
                continue
            parsed = _parse_gga(line, self._clock())
            if parsed is not None:
                fix = parsed
        return fix


class Bno055Device(Protocol):
    """Duck-typed shape of an Adafruit CircuitPython BNO055 device
    object. Both properties return (None, None, None) when a fresh
    reading isn't currently available (e.g. not yet calibrated).
    """

    @property
    def euler(self) -> tuple[float | None, float | None, float | None]: ...
    @property
    def linear_acceleration(self) -> tuple[float | None, float | None, float | None]: ...


class HardwareImuSource:
    """Axis choice for forward acceleration (the second/Y element of
    linear_acceleration) assumes a specific physical mounting
    orientation -- confirm once physically mounted and adjust the index
    if the sign/axis turns out wrong.
    """

    def __init__(self, device: Bno055Device, clock: Callable[[], float] = time.monotonic) -> None:
        self._device = device
        self._clock = clock
        self._last_reading = ImuReading(heading_deg=0.0, forward_acceleration_mps2=0.0, timestamp=0.0)

    def read(self) -> ImuReading:
        heading, _roll, _pitch = self._device.euler
        _ax, forward_accel, _az = self._device.linear_acceleration
        if heading is None or forward_accel is None:
            return self._last_reading
        reading = ImuReading(
            heading_deg=heading % 360.0,
            forward_acceleration_mps2=forward_accel,
            timestamp=self._clock(),
        )
        self._last_reading = reading
        return reading
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_hardware_sensor_hub.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/hardware_sensor_hub.py pathfinder-autonomous/pi-mission/tests/test_hardware_sensor_hub.py
git commit -m "feat(pi-mission): add hardware GPS (NMEA GGA) and IMU (BNO055) sensor sources"
```

---

### Task 3: Ultrasonic + camera hardware sources, and the bundled SensorHub

**Files:**
- Modify: `pathfinder-autonomous/pi-mission/papaya_mission/hardware_sensor_hub.py`
- Modify: `pathfinder-autonomous/pi-mission/tests/test_hardware_sensor_hub.py`

**Interfaces:**
- Consumes: `papaya_mission.sensor_hub.ObstacleDetection` (unchanged); `HardwareGpsSource`, `HardwareImuSource` from Task 2.
- Produces: `PulseMeasurer` (`Protocol`: `measure_echo_pulse_us() -> float | None`), `HardwareUltrasonicSource(pulse_measurer: PulseMeasurer)` implementing `UltrasonicSource`; `ClassifierSource` (`Protocol`: `classify() -> tuple[str, float] | None`), `HardwareCameraSource(classifier_source: ClassifierSource)` implementing `CameraSource`; `HardwareSensorHub(gps, imu, ultrasonic, camera)` bundling all four into one `SensorHub`-conforming object. Task 5 passes a `HardwareSensorHub` instance straight to `MissionRuntime(sensor_hub=...)`.

- [ ] **Step 1: Write the failing tests**

Append to `test_hardware_sensor_hub.py`:

```python
from papaya_mission.hardware_sensor_hub import (
    HardwareCameraSource,
    HardwareSensorHub,
    HardwareUltrasonicSource,
)


class _FakePulseMeasurer:
    def __init__(self, pulse_us: float | None) -> None:
        self._pulse_us = pulse_us

    def measure_echo_pulse_us(self) -> float | None:
        return self._pulse_us


def test_ultrasonic_returns_none_when_no_echo():
    source = HardwareUltrasonicSource(pulse_measurer=_FakePulseMeasurer(None))

    assert source.read() is None


def test_ultrasonic_converts_pulse_width_to_range_with_zero_bearing():
    # Standard HC-SR04 formula: distance_cm = pulse_width_us / 58.0.
    # 580us / 58.0 = 10cm = 0.1m.
    source = HardwareUltrasonicSource(pulse_measurer=_FakePulseMeasurer(580.0))

    detection = source.read()

    assert detection is not None
    assert detection.relative_bearing_deg == 0.0
    assert detection.range_m == 0.1


class _FakeClassifierSource:
    def __init__(self, result: tuple[str, float] | None) -> None:
        self._result = result

    def classify(self) -> tuple[str, float] | None:
        return self._result


def test_camera_returns_none_when_nothing_classified():
    source = HardwareCameraSource(classifier_source=_FakeClassifierSource(None))

    assert source.read() is None


def test_camera_passes_through_a_classification():
    source = HardwareCameraSource(classifier_source=_FakeClassifierSource(("barrel", 0.9)))

    assert source.read() == ("barrel", 0.9)


def test_hardware_sensor_hub_bundles_all_four_sources():
    gps = HardwareGpsSource(line_source=_FakeLineSource([]), clock=lambda: 1.0)
    imu = HardwareImuSource(device=_FakeBno055Device(), clock=lambda: 1.0)
    ultrasonic = HardwareUltrasonicSource(pulse_measurer=_FakePulseMeasurer(None))
    camera = HardwareCameraSource(classifier_source=_FakeClassifierSource(None))

    hub = HardwareSensorHub(gps=gps, imu=imu, ultrasonic=ultrasonic, camera=camera)

    assert hub.gps is gps
    assert hub.imu is imu
    assert hub.ultrasonic is ultrasonic
    assert hub.camera is camera
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_hardware_sensor_hub.py -v`
Expected: FAIL — `ImportError: cannot import name 'HardwareUltrasonicSource'` (and similarly for `HardwareCameraSource`/`HardwareSensorHub`)

- [ ] **Step 3: Write the implementation**

Add to `hardware_sensor_hub.py`'s imports:

```python
from papaya_mission.sensor_hub import ObstacleDetection
```

Append these classes to the file:

```python
class PulseMeasurer(Protocol):
    """Triggers the ultrasonic sensor and returns the echo pulse width
    in microseconds, or None if no echo was received (nothing in
    range). The real implementation (a pigpio-timed TRIG/ECHO sequence
    through the voltage divider) is bench-time work.
    """

    def measure_echo_pulse_us(self) -> float | None: ...


class HardwareUltrasonicSource:
    """The bench rig has no mast-rotation servo wired (see
    docs/wiring/breadboard-wiring-layout.yaml) -- the sensor is simply
    forward-facing, so relative_bearing_deg is always 0.0 here.
    """

    def __init__(self, pulse_measurer: PulseMeasurer) -> None:
        self._pulse_measurer = pulse_measurer

    def read(self) -> ObstacleDetection | None:
        pulse_us = self._pulse_measurer.measure_echo_pulse_us()
        if pulse_us is None:
            return None
        range_m = (pulse_us / 58.0) / 100.0
        return ObstacleDetection(relative_bearing_deg=0.0, range_m=range_m)


class ClassifierSource(Protocol):
    """Returns the current camera classification, or None if nothing is
    classified this read. The real Pi AI Camera / picamera2 / IMX500
    backend is bench-time work -- its API is fast-moving and best
    confirmed against the actual camera and current docs, not guessed
    at here. Any real implementation that satisfies this shape drops in
    without changing HardwareCameraSource.
    """

    def classify(self) -> tuple[str, float] | None: ...


class HardwareCameraSource:
    def __init__(self, classifier_source: ClassifierSource) -> None:
        self._classifier_source = classifier_source

    def read(self) -> tuple[str, float] | None:
        return self._classifier_source.classify()


class HardwareSensorHub:
    def __init__(self, gps, imu, ultrasonic, camera) -> None:
        self.gps = gps
        self.imu = imu
        self.ultrasonic = ultrasonic
        self.camera = camera
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_hardware_sensor_hub.py -v`
Expected: PASS (13 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/hardware_sensor_hub.py pathfinder-autonomous/pi-mission/tests/test_hardware_sensor_hub.py
git commit -m "feat(pi-mission): add hardware ultrasonic/camera sources and bundle HardwareSensorHub"
```

---

### Task 4: LCD status display

**Files:**
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/status_display.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_status_display.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (independent of the sensor/link drivers — it reads a plain `dict[str, Any]` state snapshot, the same shape as what feeds `build_telemetry_record`).
- Produces: `LcdWriter` (`Protocol`: `write_lines(line1: str, line2: str) -> None`), `Screen` (frozen dataclass: `name: str`, `render: Callable[[dict], tuple[str, str]]`, `function_actions: dict[int, Callable[[dict], None]]`), `DEFAULT_SCREENS: list[Screen]`, `StatusDisplay(lcd: LcdWriter, screens: list[Screen] | None = None)` with `.current_screen`, `.next_screen()`, `.previous_screen()`, `.press_function_button(index: int, state: dict)`, `.refresh(state: dict)`.

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_status_display.py
from papaya_mission.status_display import Screen, StatusDisplay


class _FakeLcdWriter:
    def __init__(self) -> None:
        self.writes: list[tuple[str, str]] = []

    def write_lines(self, line1: str, line2: str) -> None:
        self.writes.append((line1, line2))


def _make_test_screens() -> list[Screen]:
    actions_taken = []
    return [
        Screen(name="a", render=lambda state: ("A1", "A2")),
        Screen(
            name="b",
            render=lambda state: ("B1", "B2"),
            function_actions={0: lambda state: actions_taken.append(("b", 0, state))},
        ),
    ], actions_taken


def test_starts_on_the_first_screen():
    screens, _ = _make_test_screens()
    display = StatusDisplay(lcd=_FakeLcdWriter(), screens=screens)

    assert display.current_screen.name == "a"


def test_next_screen_wraps_around():
    screens, _ = _make_test_screens()
    display = StatusDisplay(lcd=_FakeLcdWriter(), screens=screens)

    display.next_screen()
    assert display.current_screen.name == "b"
    display.next_screen()
    assert display.current_screen.name == "a"


def test_previous_screen_wraps_around():
    screens, _ = _make_test_screens()
    display = StatusDisplay(lcd=_FakeLcdWriter(), screens=screens)

    display.previous_screen()
    assert display.current_screen.name == "b"


def test_refresh_writes_the_current_screens_render_output():
    screens, _ = _make_test_screens()
    lcd = _FakeLcdWriter()
    display = StatusDisplay(lcd=lcd, screens=screens)

    display.refresh(state={})

    assert lcd.writes == [("A1", "A2")]


def test_refresh_truncates_lines_longer_than_16_characters():
    screens = [Screen(name="long", render=lambda state: ("A" * 20, "B" * 20))]
    lcd = _FakeLcdWriter()
    display = StatusDisplay(lcd=lcd, screens=screens)

    display.refresh(state={})

    line1, line2 = lcd.writes[0]
    assert len(line1) == 16
    assert len(line2) == 16


def test_function_button_dispatches_to_the_current_screens_action():
    screens, actions_taken = _make_test_screens()
    display = StatusDisplay(lcd=_FakeLcdWriter(), screens=screens)
    display.next_screen()  # move to screen "b", which has a function_actions[0]

    display.press_function_button(0, state={"key": "value"})

    assert actions_taken == [("b", 0, {"key": "value"})]


def test_function_button_with_no_action_for_that_index_does_nothing():
    screens, actions_taken = _make_test_screens()
    display = StatusDisplay(lcd=_FakeLcdWriter(), screens=screens)
    display.next_screen()  # screen "b" only has an action for index 0

    display.press_function_button(1, state={})

    assert actions_taken == []


def test_default_screens_render_without_raising_on_an_empty_state():
    from papaya_mission.status_display import DEFAULT_SCREENS

    for screen in DEFAULT_SCREENS:
        line1, line2 = screen.render({})
        assert isinstance(line1, str)
        assert isinstance(line2, str)
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_status_display.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'papaya_mission.status_display'`

- [ ] **Step 3: Write the implementation**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/status_display.py
"""LCD status display: a small set of screens cycled by up/down
buttons, with 2 function buttons whose meaning depends on the current
screen (soft-key style) -- see design spec:
docs/superpowers/specs/2026-09-30-breadboard-bench-rig-design.md.

Reads the same state MissionRuntime already assembles into telemetry
each tick -- no separate data path. The LCD write backend (the real
1602A/PCF8574 byte-banged protocol -- see github.com/UCTRONICS/KB0005
for the confirmed reference) is injected via the constructor, so every
screen/navigation/dispatch rule here is testable without a real LCD.
Building the real PCF8574 writer is bench-time work, not done here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


class LcdWriter(Protocol):
    """Writes exactly two lines (already truncated to the display's
    width) to the physical LCD.
    """

    def write_lines(self, line1: str, line2: str) -> None: ...


@dataclass(frozen=True)
class Screen:
    name: str
    render: Callable[[dict[str, Any]], tuple[str, str]]
    # Maps function-button index (0 or 1) to an action taken on press.
    # A screen with no entry for a given index does nothing on that
    # button -- not every screen needs to use both function buttons.
    function_actions: dict[int, Callable[[dict[str, Any]], None]] = field(default_factory=dict)


def _render_position(state: dict[str, Any]) -> tuple[str, str]:
    position = state.get("position")
    heading = state.get("heading_deg")
    if position is None or heading is None:
        return ("GPS: no fix", "")
    lon, lat = position
    return (f"{lat:.5f},{lon:.5f}", f"Hdg {heading:.0f} deg")


def _render_mission(state: dict[str, Any]) -> tuple[str, str]:
    alert = state.get("mission_alert") or "none"
    nav_mode = state.get("nav_mode", "idle")
    return (f"Mode: {nav_mode}", f"Alert: {alert}")


def _render_obstacles(state: dict[str, Any]) -> tuple[str, str]:
    count = state.get("obstacle_count", 0)
    last_type = state.get("last_obstacle_type", "-")
    return (f"Obstacles: {count}", f"Last: {last_type}")


def _render_drive(state: dict[str, Any]) -> tuple[str, str]:
    throttle = state.get("throttle_position", 0.0)
    halted = state.get("halted_on_contact", False)
    return (f"Throttle: {throttle:.2f}", "HALTED" if halted else "running")


DEFAULT_SCREENS: list[Screen] = [
    Screen(name="position", render=_render_position),
    Screen(name="mission", render=_render_mission),
    Screen(name="obstacles", render=_render_obstacles),
    Screen(name="drive", render=_render_drive),
]


class StatusDisplay:
    def __init__(self, lcd: LcdWriter, screens: list[Screen] | None = None) -> None:
        self._lcd = lcd
        self._screens = screens if screens is not None else DEFAULT_SCREENS
        self._index = 0

    @property
    def current_screen(self) -> Screen:
        return self._screens[self._index]

    def next_screen(self) -> None:
        self._index = (self._index + 1) % len(self._screens)

    def previous_screen(self) -> None:
        self._index = (self._index - 1) % len(self._screens)

    def press_function_button(self, index: int, state: dict[str, Any]) -> None:
        action = self.current_screen.function_actions.get(index)
        if action is not None:
            action(state)

    def refresh(self, state: dict[str, Any]) -> None:
        line1, line2 = self.current_screen.render(state)
        self._lcd.write_lines(line1[:16], line2[:16])
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_status_display.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/status_display.py pathfinder-autonomous/pi-mission/tests/test_status_display.py
git commit -m "feat(pi-mission): add LCD status display with screen navigation and soft-key dispatch"
```

---

### Task 5: End-to-end wiring against a real MissionRuntime

**Files:**
- Create: `pathfinder-autonomous/pi-mission/tests/test_hardware_drivers_integration.py`

**Interfaces:**
- Consumes: `HardwareSensorHub`, `HardwareGpsSource`, `HardwareImuSource`, `HardwareUltrasonicSource`, `HardwareCameraSource` from Tasks 2-3; `HardwareEsp32Link` from Task 1; `papaya_mission.runtime.MissionRuntime`. Follows the same `_make_started_runtime` fixture pattern as `tests/test_runtime_tick_sensing.py` and `tests/test_digital_twin_scenarios.py`.
- Produces: nothing consumed by later tasks — this is the final task in the plan.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run the tests and verify they pass**

Run: `pytest tests/test_hardware_drivers_integration.py -v`
Expected: PASS — this task adds no new production code, only a test exercising Tasks 1-4's classes against a real `MissionRuntime`. Treat an unexpected failure here as a real integration bug to fix, not a step to skip.

- [ ] **Step 3: (No new implementation)**

This task only proves the four driver classes genuinely satisfy `SensorHub`/`Esp32Link` and that `MissionRuntime` ticks cleanly against them — the same role `tests/test_digital_twin_scenarios.py` played for the digital twin.

- [ ] **Step 4: Run the full test suite and verify everything passes**

Run: `pytest -v` (from `pathfinder-autonomous/pi-mission/`)
Expected: PASS — all prior tests plus this plan's new ones (9 + 8 + 5 + 8 + 1 = 31 new tests).

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/tests/test_hardware_drivers_integration.py
git commit -m "test(pi-mission): add end-to-end hardware-driver integration test against MissionRuntime"
```
