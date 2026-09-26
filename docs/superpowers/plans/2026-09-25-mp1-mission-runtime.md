# MP-1 Mission Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the orchestrator process that runs on the Pi and ties together the four already-approved Pi-mission plans (Position & Coverage Geometry, Obstacle Detection & Classification, Mission Flow Decision Logic, Pi Local Store & Sync Client) and the Backend Core HTTP API into one running mission: startup/resume, a single-threaded tick loop driving sensing/position/obstacle-detection/decision logic, mid-mission command handling, and Home-return sync.

**Architecture:** A thin `MissionRuntime` orchestrator class (`runtime.py`) that sequences calls into the already-tested modules from the four dependent plans — it owns no business logic of its own, only wiring and sequencing. Two new interface boundaries make the hardware/network edges testable without real hardware or a live backend: `sensor_hub.py` (GPS/IMU/ultrasonic/camera as `Protocol` interfaces, with a `SimulatedSensorHub` fake for tests) and `esp32_link.py` (the Pi↔ESP32 contract, with an in-memory fake). A new `backend_client.py` owns the read/poll half of talking to the Backend Core API (fetching rover/geofence config, polling/acking commands) — `sync_client.py` from the Pi Local Store & Sync Client plan already owns the push half.

**Tech Stack:** Python 3.11, Shapely 2.x, httpx, pytest, python-dotenv. No new dependencies beyond what the four dependent plans and Backend Core already established.

## Global Constraints

- Extends `pathfinder-autonomous/pi-mission/` — same `papaya_mission` package, same stack as the four prior Pi-mission plans. This plan cannot be implemented before those four plans and the Backend Core plan exist as code — it imports from all of them.
- **Execution model:** single-threaded synchronous tick loop, not asyncio or multi-threading. (Design notes: Decisions made so far.)
- **Loop timing**, named constants in `runtime_config.py`, all easily overridable: `TICK_HZ = 10` (100ms tick), `COMMAND_POLL_INTERVAL_S = 1.0`, `TELEMETRY_SAMPLE_INTERVAL_S = 5.0`. Per-tick duration must be logged — the concrete, measured trigger for revisiting the single-threaded model if later mission packages add enough work that ticks start missing their budget. (Design notes: Scaling note.)
- **GPS-loss thresholds**, named constants: `GPS_LOSS_GRACE_PERIOD_S = 30.0`, `GPS_LOSS_MAX_ERROR_RADIUS_M = 5.0` — whichever is hit first triggers `stop_and_alert` via `gps_loss_decision.decide_gps_loss_response`. (User decision, 2026-09-25.)
- **Bump-sensor safety ownership:** the ESP32 halts the drive train autonomously via a hardware interrupt, independent of the Pi link. `Esp32Link` never commands a stop — `poll_bump_events()`/`status()` only ever report a stop that already happened. A dropped Pi↔ESP32 link is therefore never a safety event in this plan's error handling — only a telemetry/logging gap. (Design notes: Bump-sensor safety ownership; approved MP-1 design spec: Architecture — Sensing.)
- **Fault isolation:** a failure reading one sensor, polling commands, or syncing to the backend must never stop the mission — log it, treat it as a momentary "missing" reading for that tick, and continue. This is what the local-store store-and-forward design exists to tolerate. (Design notes: Error handling.)
- `pause_sweep` keeps the rover's backend `status="active"` (the Backend Core plan's command service no longer deactivates on pause); only `stop_sweep`/`abort_home` release it, and `resume_sweep` re-asserts it. Mission Runtime's own `SweepSession.interrupt()`/`.resume()` calls must line up with this: pausing calls `interrupt()`, resuming calls `.resume()`, without touching backend rover activation itself (the backend's command service already handles that side of the invariant when the command is enqueued).
- Coordinate order is `[longitude, latitude]` everywhere GeoJSON appears (backend responses, `local_store` records' `position`/`pattern` fields), matching every other plan in this phase.
- No mocking of anything with a real correctness property: `sensor_hub.py`/`esp32_link.py` fakes stand in for hardware (there is no real hardware yet), `backend_client.py`/`sync_client.py` use `httpx.MockTransport` (no live server), but every pure-logic module this plan calls into (`position_fusion`, `sweep_session`, `classification`, decision functions, `local_store`'s real SQLite) runs for real in tests, per the pattern already established by the four dependent plans.

---

## File Structure

```
pathfinder-autonomous/
  pi-mission/
    papaya_mission/
      runtime_config.py    # NEW -- named constants, .env-loaded settings
      sensor_hub.py          # NEW -- GpsSource/ImuSource/UltrasonicSource/CameraSource
                              #        Protocols + SimulatedSensorHub fake
      esp32_link.py            # NEW -- Esp32Link Protocol + FakeEsp32Link
      backend_client.py         # NEW -- fetch_rover/fetch_geofence/list_geofences/
                                 #        poll_commands/ack_command
      runtime.py                 # NEW -- MissionRuntime orchestrator
    __main__.py                   # NEW -- CLI entrypoint (repo root, not inside the package)
    tests/
      test_runtime_config.py       # NEW
      test_sensor_hub.py             # NEW
      test_esp32_link.py              # NEW
      test_backend_client.py           # NEW
      test_runtime_startup.py           # NEW
      test_runtime_resume.py             # NEW
      test_runtime_tick_sensing.py        # NEW
      test_runtime_tick_commands.py        # NEW
      test_runtime_sync_and_integration.py  # NEW
```

A note on why `backend_client.py` exists at all: none of the four dependent plans include a client for *reading* from the backend (fetching the active rover's config, fetching a geofence, polling/acking commands) — `sync_client.py` only *pushes* data up. This plan needs both directions.

---

### Task 1: Runtime configuration

**Files:**
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/runtime_config.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_runtime_config.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `papaya_mission.runtime_config.{TICK_HZ, TICK_INTERVAL_S, COMMAND_POLL_INTERVAL_S, TELEMETRY_SAMPLE_INTERVAL_S, GPS_LOSS_GRACE_PERIOD_S, GPS_LOSS_MAX_ERROR_RADIUS_M, SENSOR_DETECTION_WIDTH_M, RuntimeSettings, load_runtime_settings() -> RuntimeSettings}`. `RuntimeSettings` has fields `rover_id: str`, `backend_base_url: str`, `local_db_path: str`. Every later task imports the named constants directly and calls `load_runtime_settings()` once at startup (Task 9's `__main__.py`).

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_runtime_config.py
import os

import pytest

from papaya_mission import runtime_config


def test_tick_interval_matches_tick_hz():
    assert runtime_config.TICK_INTERVAL_S == pytest.approx(1.0 / runtime_config.TICK_HZ)


def test_load_runtime_settings_reads_env(monkeypatch):
    monkeypatch.setenv("ROVER_ID", "rover-123")
    monkeypatch.setenv("BACKEND_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("LOCAL_DB_PATH", "/tmp/papaya.db")

    settings = runtime_config.load_runtime_settings()

    assert settings.rover_id == "rover-123"
    assert settings.backend_base_url == "http://localhost:8000"
    assert settings.local_db_path == "/tmp/papaya.db"


def test_load_runtime_settings_raises_on_missing_env(monkeypatch):
    monkeypatch.delenv("ROVER_ID", raising=False)
    monkeypatch.delenv("BACKEND_BASE_URL", raising=False)
    monkeypatch.delenv("LOCAL_DB_PATH", raising=False)

    with pytest.raises(KeyError):
        runtime_config.load_runtime_settings()
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_runtime_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'papaya_mission.runtime_config'`

- [ ] **Step 3: Write the implementation**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/runtime_config.py
"""Runtime-wide named constants and .env-loaded settings for Mission
Runtime. See design notes: Decisions made so far, Global Constraints.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

# --- Loop timing -----------------------------------------------------------
# All overridable by editing this file. See design notes' "Scaling note"
# for the revisit trigger if TICK_HZ's 100ms budget ever gets tight.
TICK_HZ = 10
TICK_INTERVAL_S = 1.0 / TICK_HZ
COMMAND_POLL_INTERVAL_S = 1.0
TELEMETRY_SAMPLE_INTERVAL_S = 5.0

# --- GPS-loss safety thresholds ----------------------------------------------
# Whichever is hit first triggers stop_and_alert -- see
# papaya_mission.gps_loss_decision.decide_gps_loss_response.
GPS_LOSS_GRACE_PERIOD_S = 30.0
GPS_LOSS_MAX_ERROR_RADIUS_M = 5.0

# --- Coverage-pattern input ---------------------------------------------------
# Ultrasonic sensor's effective detection width in meters, sets row
# spacing (papaya_mission.row_spacing). PLACEHOLDER: the actual
# ultrasonic sensor part hasn't been selected yet (open item in the MP-1
# design spec's BOM) -- update this once it is.
SENSOR_DETECTION_WIDTH_M = 2.0


@dataclass(frozen=True)
class RuntimeSettings:
    rover_id: str
    backend_base_url: str
    local_db_path: str


def load_runtime_settings() -> RuntimeSettings:
    """Reads ROVER_ID/BACKEND_BASE_URL/LOCAL_DB_PATH from the environment
    (via .env, same convention as pathfinder-autonomous/backend/). Raises
    KeyError if any is missing -- fail loudly rather than silently
    defaulting to a placeholder that could mask a real misconfiguration.
    """
    return RuntimeSettings(
        rover_id=os.environ["ROVER_ID"],
        backend_base_url=os.environ["BACKEND_BASE_URL"],
        local_db_path=os.environ["LOCAL_DB_PATH"],
    )
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_runtime_config.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/runtime_config.py pathfinder-autonomous/pi-mission/tests/test_runtime_config.py
git commit -m "feat(pi-mission): add Mission Runtime named constants and .env settings"
```

---

### Task 2: Sensor hub interfaces

**Files:**
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/sensor_hub.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_sensor_hub.py`

**Interfaces:**
- Consumes: `papaya_mission.position_fusion.{GpsFix, ImuReading}` (Position & Coverage Geometry plan).
- Produces: `papaya_mission.sensor_hub.{ObstacleDetection, GpsSource, ImuSource, UltrasonicSource, CameraSource, SensorHub, SimulatedSensorHub}`. `ObstacleDetection` carries `relative_bearing_deg: float, range_m: float`. `UltrasonicSource.read() -> ObstacleDetection | None` gives bearing/range only; `CameraSource.read() -> tuple[str, float] | None` gives `(classified_type, confidence)` — Task 7 pairs a same-tick ultrasonic + camera reading into one `obstacle_detection.obstacle_from_ultrasonic_camera_detection(...)` call (real hardware will likely correlate these at the driver level; that correlation is out of scope here, deferred with the rest of hardware integration). `SimulatedSensorHub(initial_imu: ImuReading)` has `.script_gps_fix(fix)`, `.script_imu_reading(reading)`, `.script_ultrasonic(detection)`, `.script_camera(classification)` — each scripted value is returned exactly once by the corresponding source's next `.read()()` call, then cleared (mirrors a real sensor's "read the latest sample" semantics, not a replayable queue). Every later task's tests construct a `SimulatedSensorHub` and inject it into `MissionRuntime`.

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_sensor_hub.py
from papaya_mission.position_fusion import GpsFix, ImuReading
from papaya_mission.sensor_hub import ObstacleDetection, SimulatedSensorHub

INITIAL_IMU = ImuReading(heading_deg=0.0, forward_acceleration_mps2=0.0, timestamp=0.0)


def test_gps_source_returns_none_until_scripted():
    hub = SimulatedSensorHub(INITIAL_IMU)

    assert hub.gps.read() is None


def test_gps_source_returns_scripted_fix_once():
    hub = SimulatedSensorHub(INITIAL_IMU)
    fix = GpsFix(lat=38.0, lon=-85.0, accuracy_m=2.0, timestamp=1.0)
    hub.script_gps_fix(fix)

    assert hub.gps.read() == fix
    assert hub.gps.read() is None


def test_imu_source_returns_latest_scripted_reading_every_time():
    hub = SimulatedSensorHub(INITIAL_IMU)
    reading = ImuReading(heading_deg=90.0, forward_acceleration_mps2=1.0, timestamp=1.0)
    hub.script_imu_reading(reading)

    assert hub.imu.read() == reading
    assert hub.imu.read() == reading  # IMU always has a "current" reading, unlike GPS


def test_ultrasonic_and_camera_sources_consume_once():
    hub = SimulatedSensorHub(INITIAL_IMU)
    detection = ObstacleDetection(relative_bearing_deg=15.0, range_m=2.5)
    hub.script_ultrasonic(detection)
    hub.script_camera(("barrel", 0.9))

    assert hub.ultrasonic.read() == detection
    assert hub.ultrasonic.read() is None
    assert hub.camera.read() == ("barrel", 0.9)
    assert hub.camera.read() is None
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_sensor_hub.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'papaya_mission.sensor_hub'`

- [ ] **Step 3: Write the implementation**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/sensor_hub.py
"""GPS/IMU/ultrasonic/camera sensor interfaces Mission Runtime reads
from each tick. Real hardware drivers are deferred to a future
hardware-integration pass, same as every other Pi-mission plan treats
sensor acquisition -- these Protocols are the contract a real driver
will eventually implement; SimulatedSensorHub is the test double used
until then.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from papaya_mission.position_fusion import GpsFix, ImuReading


@dataclass(frozen=True)
class ObstacleDetection:
    relative_bearing_deg: float
    range_m: float


class GpsSource(Protocol):
    def read(self) -> GpsFix | None: ...


class ImuSource(Protocol):
    def read(self) -> ImuReading: ...


class UltrasonicSource(Protocol):
    def read(self) -> ObstacleDetection | None: ...


class CameraSource(Protocol):
    def read(self) -> tuple[str, float] | None: ...


class SensorHub(Protocol):
    gps: GpsSource
    imu: ImuSource
    ultrasonic: UltrasonicSource
    camera: CameraSource


class SimulatedSensorHub:
    """In-memory fake for tests. Each scripted value is consumed exactly
    once by the next matching .read() call, except the IMU which always
    has a "current" reading (a real IMU has no concept of "no reading
    yet" the way GPS/ultrasonic/camera do).
    """

    def __init__(self, initial_imu: ImuReading) -> None:
        self._next_gps_fix: GpsFix | None = None
        self._current_imu_reading = initial_imu
        self._next_ultrasonic: ObstacleDetection | None = None
        self._next_camera: tuple[str, float] | None = None
        self.gps: GpsSource = _SimGpsSource(self)
        self.imu: ImuSource = _SimImuSource(self)
        self.ultrasonic: UltrasonicSource = _SimUltrasonicSource(self)
        self.camera: CameraSource = _SimCameraSource(self)

    def script_gps_fix(self, fix: GpsFix | None) -> None:
        self._next_gps_fix = fix

    def script_imu_reading(self, reading: ImuReading) -> None:
        self._current_imu_reading = reading

    def script_ultrasonic(self, detection: ObstacleDetection | None) -> None:
        self._next_ultrasonic = detection

    def script_camera(self, classification: tuple[str, float] | None) -> None:
        self._next_camera = classification


class _SimGpsSource:
    def __init__(self, hub: SimulatedSensorHub) -> None:
        self._hub = hub

    def read(self) -> GpsFix | None:
        fix, self._hub._next_gps_fix = self._hub._next_gps_fix, None
        return fix


class _SimImuSource:
    def __init__(self, hub: SimulatedSensorHub) -> None:
        self._hub = hub

    def read(self) -> ImuReading:
        return self._hub._current_imu_reading


class _SimUltrasonicSource:
    def __init__(self, hub: SimulatedSensorHub) -> None:
        self._hub = hub

    def read(self) -> ObstacleDetection | None:
        detection, self._hub._next_ultrasonic = self._hub._next_ultrasonic, None
        return detection


class _SimCameraSource:
    def __init__(self, hub: SimulatedSensorHub) -> None:
        self._hub = hub

    def read(self) -> tuple[str, float] | None:
        result, self._hub._next_camera = self._hub._next_camera, None
        return result
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_sensor_hub.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/sensor_hub.py pathfinder-autonomous/pi-mission/tests/test_sensor_hub.py
git commit -m "feat(pi-mission): add sensor hub interfaces with simulated fake for tests"
```

---

### Task 3: ESP32 link interface

**Files:**
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/esp32_link.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_esp32_link.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `papaya_mission.esp32_link.{BumpEvent, Esp32Status, Esp32Link, FakeEsp32Link}`. `BumpEvent` carries `detected_at: datetime`. `Esp32Status` carries `halted_on_contact: bool`. `Esp32Link` Protocol: `poll_bump_events() -> list[BumpEvent]`, `status() -> Esp32Status`, `send_geofence_update(exclusion_zone_ids: list[str]) -> None`, `trigger_ota(firmware_path: str) -> None`. This is a contract only — the real UART/I2C wire protocol is the not-yet-written ESP32 firmware plan's job, designed to match this. `FakeEsp32Link` is the in-memory test double: `.script_bump_events(events)`, `.script_status(status)` set what the next calls return; `.geofence_updates_sent`/`.ota_triggers` record calls for assertion. `status()` is what lets Mission Runtime check for a halted-on-contact state after a link outage before resuming movement commands (design notes: Error handling).

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_esp32_link.py
from datetime import datetime, timezone

from papaya_mission.esp32_link import BumpEvent, Esp32Status, FakeEsp32Link


def test_poll_bump_events_returns_empty_by_default():
    link = FakeEsp32Link()

    assert link.poll_bump_events() == []


def test_poll_bump_events_returns_scripted_events_once():
    link = FakeEsp32Link()
    event = BumpEvent(detected_at=datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc))
    link.script_bump_events([event])

    assert link.poll_bump_events() == [event]
    assert link.poll_bump_events() == []


def test_status_defaults_to_not_halted():
    link = FakeEsp32Link()

    assert link.status() == Esp32Status(halted_on_contact=False)


def test_status_returns_scripted_value():
    link = FakeEsp32Link()
    link.script_status(Esp32Status(halted_on_contact=True))

    assert link.status() == Esp32Status(halted_on_contact=True)


def test_send_geofence_update_and_trigger_ota_are_recorded():
    link = FakeEsp32Link()

    link.send_geofence_update(["zone-1", "zone-2"])
    link.trigger_ota("/firmware/v2.bin")

    assert link.geofence_updates_sent == [["zone-1", "zone-2"]]
    assert link.ota_triggers == ["/firmware/v2.bin"]
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_esp32_link.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'papaya_mission.esp32_link'`

- [ ] **Step 3: Write the implementation**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/esp32_link.py
"""The Pi<->ESP32 contract Mission Runtime depends on. The ESP32 owns
bump-sensor safety autonomously (hardware interrupt cuts the drive
train directly, no Pi round-trip) -- this interface never commands a
stop, it only ever reports one that already happened. See design
notes: Bump-sensor safety ownership.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class BumpEvent:
    detected_at: datetime


@dataclass(frozen=True)
class Esp32Status:
    halted_on_contact: bool


class Esp32Link(Protocol):
    def poll_bump_events(self) -> list[BumpEvent]: ...
    def status(self) -> Esp32Status: ...
    def send_geofence_update(self, exclusion_zone_ids: list[str]) -> None: ...
    def trigger_ota(self, firmware_path: str) -> None: ...


@dataclass
class FakeEsp32Link:
    """In-memory fake for tests."""

    _scripted_bump_events: list[BumpEvent] = field(default_factory=list)
    _scripted_status: Esp32Status = field(default_factory=lambda: Esp32Status(halted_on_contact=False))
    geofence_updates_sent: list[list[str]] = field(default_factory=list)
    ota_triggers: list[str] = field(default_factory=list)

    def script_bump_events(self, events: list[BumpEvent]) -> None:
        self._scripted_bump_events = list(events)

    def script_status(self, status: Esp32Status) -> None:
        self._scripted_status = status

    def poll_bump_events(self) -> list[BumpEvent]:
        events, self._scripted_bump_events = self._scripted_bump_events, []
        return events

    def status(self) -> Esp32Status:
        return self._scripted_status

    def send_geofence_update(self, exclusion_zone_ids: list[str]) -> None:
        self.geofence_updates_sent.append(exclusion_zone_ids)

    def trigger_ota(self, firmware_path: str) -> None:
        self.ota_triggers.append(firmware_path)
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_esp32_link.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/esp32_link.py pathfinder-autonomous/pi-mission/tests/test_esp32_link.py
git commit -m "feat(pi-mission): add ESP32 link interface with fake for tests"
```

---

### Task 4: Backend read/poll client

**Files:**
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/backend_client.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_backend_client.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (uses `httpx` directly, same dependency `sync_client.py` already added).
- Produces: `papaya_mission.backend_client.{fetch_rover(client, base_url, rover_id) -> dict, fetch_geofence(client, base_url, geofence_id) -> dict, list_geofences(client, base_url) -> list[dict], poll_commands(client, base_url, rover_id) -> list[dict], ack_command(client, base_url, command_id) -> dict}`. All return plain dicts parsed straight from the Backend Core API's JSON responses — no parallel dataclass hierarchy, matching `local_store`'s established convention. `list_geofences` exists because `start_sweep` needs both the one inclusive field boundary *and* every exclusive geofence (exclusion zones) — the Backend Core plan's `point_in_any_exclusive_zone` has no HTTP exposure, so Mission Runtime fetches the full list and filters `type == "exclusive"` locally (Task 6 does this filtering). Every function calls `response.raise_for_status()` so an HTTP error surfaces as `httpx.HTTPStatusError` for the caller to catch — Task 5/8 decide what "caught" means for each call site (e.g. a 404 on `fetch_geofence` during `start_sweep` is a real problem; a poll-commands failure mid-tick is not).

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_backend_client.py
import httpx
import pytest

from papaya_mission import backend_client

BASE_URL = "http://backend.local"


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_rover_returns_json():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rovers/rover-1"
        return httpx.Response(200, json={"_id": "rover-1", "name": "George"})

    result = backend_client.fetch_rover(_client(handler), BASE_URL, "rover-1")

    assert result == {"_id": "rover-1", "name": "George"}


def test_fetch_geofence_returns_json():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/geofences/fence-1"
        return httpx.Response(200, json={"_id": "fence-1", "type": "inclusive"})

    result = backend_client.fetch_geofence(_client(handler), BASE_URL, "fence-1")

    assert result == {"_id": "fence-1", "type": "inclusive"}


def test_list_geofences_returns_json_list():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/geofences"
        return httpx.Response(200, json=[{"_id": "fence-1"}, {"_id": "fence-2"}])

    result = backend_client.list_geofences(_client(handler), BASE_URL)

    assert result == [{"_id": "fence-1"}, {"_id": "fence-2"}]


def test_poll_commands_returns_json_list():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/commands/poll/rover-1"
        return httpx.Response(200, json=[{"_id": "cmd-1", "type": "pause_sweep"}])

    result = backend_client.poll_commands(_client(handler), BASE_URL, "rover-1")

    assert result == [{"_id": "cmd-1", "type": "pause_sweep"}]


def test_ack_command_posts_and_returns_json():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/commands/cmd-1/ack"
        return httpx.Response(200, json={"_id": "cmd-1", "status": "acked"})

    result = backend_client.ack_command(_client(handler), BASE_URL, "cmd-1")

    assert result == {"_id": "cmd-1", "status": "acked"}


def test_fetch_rover_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "not found"})

    with pytest.raises(httpx.HTTPStatusError):
        backend_client.fetch_rover(_client(handler), BASE_URL, "unknown")
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_backend_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'papaya_mission.backend_client'`

- [ ] **Step 3: Write the implementation**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/backend_client.py
"""Read/poll half of talking to the Backend Core API. sync_client.py
(Pi Local Store & Sync Client plan) is the push half. See design
notes: Architecture & file structure.
"""
from __future__ import annotations

from typing import Any

import httpx


def fetch_rover(client: httpx.Client, base_url: str, rover_id: str) -> dict[str, Any]:
    response = client.get(f"{base_url}/rovers/{rover_id}")
    response.raise_for_status()
    return response.json()


def fetch_geofence(client: httpx.Client, base_url: str, geofence_id: str) -> dict[str, Any]:
    response = client.get(f"{base_url}/geofences/{geofence_id}")
    response.raise_for_status()
    return response.json()


def list_geofences(client: httpx.Client, base_url: str) -> list[dict[str, Any]]:
    response = client.get(f"{base_url}/geofences")
    response.raise_for_status()
    return response.json()


def poll_commands(client: httpx.Client, base_url: str, rover_id: str) -> list[dict[str, Any]]:
    response = client.get(f"{base_url}/commands/poll/{rover_id}")
    response.raise_for_status()
    return response.json()


def ack_command(client: httpx.Client, base_url: str, command_id: str) -> dict[str, Any]:
    response = client.post(f"{base_url}/commands/{command_id}/ack")
    response.raise_for_status()
    return response.json()
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_backend_client.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/backend_client.py pathfinder-autonomous/pi-mission/tests/test_backend_client.py
git commit -m "feat(pi-mission): add backend read/poll client (rover, geofences, commands)"
```

---

### Task 5: MissionRuntime construction, startup, and start_sweep

**Files:**
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/runtime.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_runtime_startup.py`

**Interfaces:**
- Consumes: `papaya_mission.runtime_config.{GPS_LOSS_GRACE_PERIOD_S, GPS_LOSS_MAX_ERROR_RADIUS_M, SENSOR_DETECTION_WIDTH_M}` (Task 1), `papaya_mission.sensor_hub.SensorHub` (Task 2), `papaya_mission.esp32_link.Esp32Link` (Task 3), `papaya_mission.backend_client.{fetch_rover, fetch_geofence, list_geofences}` (Task 4), `papaya_mission.row_spacing.derive_row_spacing_m`, `papaya_mission.coverage_pattern.generate_coverage_pattern`, `papaya_mission.sweep_session.{SweepSession, SweepSessionStatus, Waypoint}` (Mission Flow Decision Logic plan), `papaya_mission.local_store.{connect, save_sweep_session, list_unsynced_sweep_sessions}` (Pi Local Store & Sync Client plan).
- Produces: `papaya_mission.runtime.MissionRuntime`. Constructor: `MissionRuntime(rover_id: str, backend_base_url: str, local_db_path: str, sensor_hub: SensorHub, esp32_link: Esp32Link, http_client: httpx.Client | None = None)`. Public methods this task adds: `.startup() -> None` (fetches rover config, connects local storage, checks for an in-progress session — Task 6 fills in the resume branch, this task's `.startup()` only handles "none found, stay idle"), `.handle_start_sweep(payload: dict) -> None` (builds a new `SweepSession` from a geofence id and persists it). Attributes later tasks rely on: `.rover: dict | None`, `.expected_metrics: set[str]`, `.sweep_session: SweepSession | None`, `.exclusion_polygons: list[shapely.geometry.Polygon]`, `.conn: sqlite3.Connection`, `.http_client: httpx.Client`.

> **Correction applied in the final fix wave** (see
> `.superpowers/sdd/2026-09-25-mp1-mission-runtime/final-fix-wave-report.md`).
> `.expected_metrics` as originally specified was built purely from the
> rover's `sensor_manifest` — i.e. physical sensor *names* (`gps`, `imu`,
> `bump`). Those names never match the derived telemetry keys Task 8 actually
> samples, and `build_telemetry_record` treats the expected set as both floor
> and ceiling, so every real reading was dropped and each record stored as
> all-`"missing"`. `startup()` now unions the manifest-derived set with a new
> named `runtime_config.MP1_EXPECTED_METRICS` constant holding MP-1's derived
> telemetry keys (`position`, `position_uncertainty_m`, `heading_deg`,
> `error_radius_m`, `nav_mode`, `waypoint_index`, `throttle_position`,
> `mission_alert`). `test_startup_fetches_rover_and_builds_expected_metrics`
> was updated to assert the union rather than `{"gps", "imu"}` alone.

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_runtime_startup.py
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
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_runtime_startup.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'papaya_mission.runtime'`

- [ ] **Step 3: Write the implementation**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/runtime.py
"""MissionRuntime: the thin orchestrator tying position fusion,
coverage/obstacle detection, mission-flow decision logic, telemetry,
and sync into one running process. Owns no business logic of its own
-- see design notes for the full architecture and mission lifecycle.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from shapely.geometry import Polygon, shape

from papaya_mission import backend_client, local_store
from papaya_mission.coverage_pattern import generate_coverage_pattern
from papaya_mission.esp32_link import Esp32Link
from papaya_mission.row_spacing import derive_row_spacing_m
from papaya_mission.runtime_config import SENSOR_DETECTION_WIDTH_M
from papaya_mission.sensor_hub import SensorHub
from papaya_mission.sweep_session import SweepSession, Waypoint


class MissionRuntime:
    def __init__(
        self,
        rover_id: str,
        backend_base_url: str,
        local_db_path: str,
        sensor_hub: SensorHub,
        esp32_link: Esp32Link,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.rover_id = rover_id
        self.backend_base_url = backend_base_url
        self.sensor_hub = sensor_hub
        self.esp32_link = esp32_link
        self.http_client = http_client or httpx.Client()
        self.conn = local_store.connect(local_db_path)

        self.rover: dict[str, Any] | None = None
        self.expected_metrics: set[str] = set()
        self.position_fusion = None  # set on start_sweep/resume (Task 6/7)
        self.sweep_session: SweepSession | None = None
        self.exclusion_polygons: list[Polygon] = []

        # Populated by later tasks; declared here so every task's tests
        # can construct a MissionRuntime against one consistent __init__.
        self._last_gps_fix_monotonic: float | None = None
        self._last_command_poll_monotonic: float = 0.0
        self._last_telemetry_sample_monotonic: float = 0.0
        self._last_telemetry_commit_at: datetime | None = None
        self._telemetry_sequence_number = 0
        self._resume_validation_target: tuple[float, float] | None = None
        self._resume_validation_collected: list[Any] = []
        # Raw local_store rows for the obstacles that were already stored
        # when a resume pass was armed. Snapshotted, not queried live -- see
        # _resume_in_progress_session_if_any (Task 6) for why.
        self._resume_validation_known_rows: list[dict[str, Any]] = []

    def startup(self) -> None:
        self.rover = backend_client.fetch_rover(self.http_client, self.backend_base_url, self.rover_id)
        self.expected_metrics = {
            entry["sensor"]
            for entry in self.rover.get("sensor_manifest", [])
            if entry.get("installed", True)
        }
        # Task 6 extends this to check local storage for an in-progress
        # session and resume it. Nothing found here yet -> stay idle,
        # waiting for start_sweep (handled by the tick loop, Task 8).

    def handle_start_sweep(self, payload: dict[str, Any]) -> None:
        geofence_id = payload["geofence_id"]
        inclusive = backend_client.fetch_geofence(self.http_client, self.backend_base_url, geofence_id)
        all_geofences = backend_client.list_geofences(self.http_client, self.backend_base_url)
        exclusive = [g for g in all_geofences if g["type"] == "exclusive"]

        inclusive_polygon = shape(inclusive["boundary"])
        self.exclusion_polygons = [shape(g["boundary"]) for g in exclusive]

        turn_style = self.rover.get("turn_style", "spin_in_place")
        min_turn_diameter_m = self.rover.get("min_turn_diameter_m")
        row_spacing_m = derive_row_spacing_m(
            sensor_detection_width_m=SENSOR_DETECTION_WIDTH_M,
            turn_style=turn_style,
            min_turn_diameter_m=min_turn_diameter_m,
        )

        legs = generate_coverage_pattern(
            inclusive_polygon, self.exclusion_polygons, row_spacing_m
        )
        self.sweep_session = SweepSession.from_legs(
            legs,
            id=str(uuid.uuid4()),
            rover_id=self.rover_id,
            geofence_id=geofence_id,
            started_at=datetime.now(timezone.utc),
        )
        self._save_sweep_session()

    def _save_sweep_session(self) -> None:
        session = self.sweep_session
        local_store.save_sweep_session(
            self.conn,
            {
                "id": session.id,
                "rover_id": session.rover_id,
                "geofence_id": session.geofence_id,
                "status": session.status.value,
                "pattern": [
                    {
                        "order": wp.order,
                        "position": {"type": "Point", "coordinates": list(wp.position)},
                        "leg_index": wp.leg_index,
                    }
                    for wp in session.pattern
                ],
                "last_completed_waypoint_index": session.last_completed_waypoint_index,
                "started_at": session.started_at,
                "interrupted_at": session.interrupted_at,
                "completed_at": session.completed_at,
            },
        )
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_runtime_startup.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/runtime.py pathfinder-autonomous/pi-mission/tests/test_runtime_startup.py
git commit -m "feat(pi-mission): add MissionRuntime startup and start_sweep handling"
```

---

### Task 6: Crash-recovery resume at startup

**Files:**
- Modify: `pathfinder-autonomous/pi-mission/papaya_mission/runtime.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_runtime_resume.py`

**Interfaces:**
- Consumes: Task 5's `MissionRuntime`, `papaya_mission.sweep_session.{SweepSession, SweepSessionStatus, Waypoint}`, `papaya_mission.local_store.list_unsynced_sweep_sessions` (a sweep session stays "unsynced" until Home-return sync, so any interrupted/in-progress one not yet synced is exactly the auto-resume candidate), `papaya_mission.local_store.list_obstacles_for_session`.
- Produces: extends `.startup()` — if local storage has a `SweepSession` with `status in ("in_progress", "interrupted")`, rebuild it in memory, re-fetch its geofences (rebuilding `.exclusion_polygons`), transition it to `IN_PROGRESS` via `.resume()` if it was `INTERRUPTED`, and arm resume-validation: `._resume_validation_target` is set to the position of the waypoint at `last_completed_waypoint_index` (or `None` if that's -1, meaning nothing to re-scan toward), `._resume_validation_collected` starts empty, and `._resume_validation_known_rows` is snapshotted from `local_store.list_obstacles_for_session` — the obstacles already stored for this session at the moment of arming, i.e. everything detected *before* the resume pass. Task 7's tick loop drains `._resume_validation_collected` and reconciles it against that snapshot via `resume_validation.reconcile_obstacles` once the rover's position comes within a fixed threshold of `._resume_validation_target`. That reconciliation is an unconditional tick step of its own (`._check_resume_validation_arrival()`), not something a detection triggers — arriving at the target having detected *nothing* is the case that produces the `cleared`/`discrepancies` report resume-validation exists for.

> **Correction applied in the final fix wave** (see
> `.superpowers/sdd/2026-09-25-mp1-mission-runtime/final-fix-wave-report.md`).
> "any interrupted/in-progress one not yet synced is exactly the auto-resume
> candidate" is true but not sufficient when there is more than one:
> `list_unsynced_sweep_sessions` has no `ORDER BY`, so the implementation's
> `candidates[0]` was SQLite insertion order rather than recency, and a stale
> interrupted session still on disk alongside a newer one could be resumed in
> preference to it. `_resume_in_progress_session_if_any` now sorts candidates
> by `started_at` descending before taking the first (recency is the caller's
> policy, not a property of the table) and logs a warning naming the ids it
> skips. The resume-validation id lookup was also re-keyed from position alone
> to `(position, type, detection_method, first_detected_at)`, so two obstacles
> at a bit-identical position cannot have their stored ids conflated.

**Design note on why resume-validation isn't a single blocking call:** the design spec says the rover "passively re-scans obstacles it passes" while transiting back to the resume point — that's inherently a multi-tick process (the rover has to physically drive there), not something `startup()` can do synchronously. This task only arms the target; Task 7 does the actual reconciliation once the rover arrives.

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_runtime_resume.py
from datetime import datetime, timezone

import httpx
import pytest

from papaya_mission.esp32_link import FakeEsp32Link
from papaya_mission.position_fusion import ImuReading
from papaya_mission.runtime import MissionRuntime
from papaya_mission.sensor_hub import SimulatedSensorHub
from papaya_mission.sweep_session import SweepSessionStatus
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
            match = next(g for g in geofences if g["_id"] == fid)
            return httpx.Response(200, json=match)
        raise AssertionError(request.url.path)

    return handler


def _make_runtime(tmp_path, rover, geofences) -> tuple[MissionRuntime, str]:
    db_path = str(tmp_path / "test.db")
    client = httpx.Client(transport=httpx.MockTransport(_handler(rover, geofences)))
    runtime = MissionRuntime(
        rover_id="rover-1",
        backend_base_url="http://backend.local",
        local_db_path=db_path,
        sensor_hub=SimulatedSensorHub(INITIAL_IMU),
        esp32_link=FakeEsp32Link(),
        http_client=client,
    )
    return runtime, db_path


def test_startup_with_no_prior_session_stays_idle(tmp_path):
    rover = {"_id": "rover-1", "name": "George"}
    runtime, _ = _make_runtime(tmp_path, rover, geofences=[])

    runtime.startup()

    assert runtime.sweep_session is None


def test_startup_auto_resumes_interrupted_session(tmp_path):
    rover = {"_id": "rover-1", "name": "George"}
    inclusive = {"_id": "fence-1", "type": "inclusive", "boundary": {"type": "Polygon", "coordinates": [FIELD_RING]}}
    runtime, db_path = _make_runtime(tmp_path, rover, geofences=[inclusive])
    local_store.save_sweep_session(
        runtime.conn,
        {
            "id": "sess-1",
            "rover_id": "rover-1",
            "geofence_id": "fence-1",
            "status": "interrupted",
            "pattern": [
                {"order": 0, "position": {"type": "Point", "coordinates": [-85.0, 38.0]}},
                {"order": 1, "position": {"type": "Point", "coordinates": [-85.0, 38.01]}},
            ],
            "last_completed_waypoint_index": 0,
            "started_at": datetime(2026, 9, 25, 10, 0, 0, tzinfo=timezone.utc),
            "interrupted_at": datetime(2026, 9, 25, 10, 5, 0, tzinfo=timezone.utc),
            "completed_at": None,
        },
    )
    local_store.save_obstacle(
        runtime.conn,
        {
            "id": "obs-pre-crash",
            "sweep_session_id": "sess-1",
            "position": (-85.0, 38.0),
            "position_uncertainty_m": 1.5,
            "type": "barrel",
            "classification_confidence": 0.9,
            "detection_method": "ultrasonic+camera",
            "status": "permanent-pending",
            "first_detected_at": datetime(2026, 9, 25, 10, 2, 0, tzinfo=timezone.utc),
            "last_confirmed_at": None,
        },
    )
    local_store.commit(runtime.conn)

    runtime.startup()

    assert runtime.sweep_session is not None
    assert runtime.sweep_session.id == "sess-1"
    assert runtime.sweep_session.status == SweepSessionStatus.IN_PROGRESS  # auto-resumed
    assert runtime.sweep_session.last_completed_waypoint_index == 0
    assert runtime._resume_validation_target == (-85.0, 38.0)  # waypoint order 0's position
    assert runtime._resume_validation_collected == []
    # The known-obstacle set is snapshotted at arm time, so it holds exactly
    # the pre-crash rows -- nothing this resume pass goes on to detect.
    assert [row["id"] for row in runtime._resume_validation_known_rows] == ["obs-pre-crash"]


def test_startup_does_not_resume_a_completed_but_unsynced_session(tmp_path):
    rover = {"_id": "rover-1", "name": "George"}
    runtime, _ = _make_runtime(tmp_path, rover, geofences=[])
    local_store.save_sweep_session(
        runtime.conn,
        {
            "id": "sess-1",
            "rover_id": "rover-1",
            "geofence_id": "fence-1",
            "status": "completed",
            "pattern": [{"order": 0, "position": {"type": "Point", "coordinates": [-85.0, 38.0]}}],
            "last_completed_waypoint_index": 0,
            "started_at": datetime(2026, 9, 25, 10, 0, 0, tzinfo=timezone.utc),
            "interrupted_at": None,
            "completed_at": datetime(2026, 9, 25, 10, 30, 0, tzinfo=timezone.utc),
        },
    )
    local_store.commit(runtime.conn)

    runtime.startup()

    assert runtime.sweep_session is None
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_runtime_resume.py -v`
Expected: FAIL — `AttributeError` / assertion failures, since `.startup()` doesn't check local storage yet.

- [ ] **Step 3: Extend `startup()` and add the resume helper**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/runtime.py
# Add these imports alongside the existing ones:
from papaya_mission.sweep_session import SweepSession, SweepSessionStatus, Waypoint

# Replace MissionRuntime.startup() with:
    def startup(self) -> None:
        self.rover = backend_client.fetch_rover(self.http_client, self.backend_base_url, self.rover_id)
        self.expected_metrics = {
            entry["sensor"]
            for entry in self.rover.get("sensor_manifest", [])
            if entry.get("installed", True)
        }
        self._resume_in_progress_session_if_any()

    def _resume_in_progress_session_if_any(self) -> None:
        candidates = [
            s
            for s in local_store.list_unsynced_sweep_sessions(self.conn)
            if s["status"] in ("in_progress", "interrupted")
        ]
        if not candidates:
            return
        session_dict = candidates[0]

        pattern = [
            Waypoint(
                order=wp["order"],
                position=tuple(wp["position"]["coordinates"]),
                leg_index=wp.get("leg_index", 0),
            )
            for wp in session_dict["pattern"]
        ]
        self.sweep_session = SweepSession(
            id=session_dict["id"],
            rover_id=session_dict["rover_id"],
            geofence_id=session_dict["geofence_id"],
            pattern=pattern,
            status=SweepSessionStatus(session_dict["status"]),
            last_completed_waypoint_index=session_dict["last_completed_waypoint_index"],
            started_at=session_dict["started_at"],
            interrupted_at=session_dict["interrupted_at"],
            completed_at=session_dict["completed_at"],
        )

        all_geofences = backend_client.list_geofences(self.http_client, self.backend_base_url)
        self.exclusion_polygons = [
            shape(g["boundary"]) for g in all_geofences if g["type"] == "exclusive"
        ]

        self._resume_validation_collected = []
        self._resume_validation_known_rows = []
        if self.sweep_session.last_completed_waypoint_index >= 0:
            resume_waypoint = next(
                wp for wp in self.sweep_session.pattern
                if wp.order == self.sweep_session.last_completed_waypoint_index
            )
            self._resume_validation_target = resume_waypoint.position
            # Snapshot the known obstacles ONCE, here, at the moment
            # resume-validation is armed -- the tick loop hasn't run yet, so
            # nothing this pass detects can be in it. Re-querying the store at
            # reconciliation time instead would be wrong: _detect_obstacles
            # defers paired detections while a pass is armed (Task 7), but bump
            # contacts still persist the moment they happen, at the rover's own
            # position. A live query would hand reconcile_obstacles those bump
            # rows as "known" obstacles sitting within metres of this pass's
            # fresh detections, and its greedy nearest-first matching would pair
            # a fresh detection with a row this same pass wrote, leaving the
            # genuinely pre-existing obstacle unmatched and wrongly reported as
            # cleared/discrepancies -- precisely the failure resume-validation
            # exists to catch. (The alternative, tagging freshly inserted ids
            # and subtracting them later, needs bookkeeping in every
            # _save_obstacle caller for the same result; the snapshot is a
            # single call at the one moment the boundary is unambiguous.)
            #
            # list_obstacles_for_session, not list_unsynced_obstacles: a
            # Home-return sync during the interrupted pass marks obstacles
            # synced, and an unsynced-only filter would drop them from the
            # known set, so reconciliation would treat each one as never-seen.
            #
            # Raw store rows, not domain objects: Obstacle has no id field
            # (ids are a persistence concern owned by local_store), so the row
            # is the only place an existing obstacle's id lives -- and a
            # confirmed re-detection has to be saved back under that id.
            self._resume_validation_known_rows = local_store.list_obstacles_for_session(
                self.conn, self.sweep_session.id
            )

        if self.sweep_session.status == SweepSessionStatus.INTERRUPTED:
            self.sweep_session.resume()
            self._save_sweep_session()
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_runtime_resume.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the full test suite for regressions**

Run: `pytest -v`
Expected: PASS (all tests from Tasks 1–6)

- [ ] **Step 6: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/runtime.py pathfinder-autonomous/pi-mission/tests/test_runtime_resume.py
git commit -m "feat(pi-mission): auto-resume in-progress sweep session on restart"
```

---

### Task 7: Tick loop — position, obstacle detection, exclusion checks

**Files:**
- Modify: `pathfinder-autonomous/pi-mission/papaya_mission/runtime.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_runtime_tick_sensing.py`

**Interfaces:**
- Consumes: `papaya_mission.position_fusion.{GpsFix, ImuReading, PositionEstimate, PositionFusion}`, `papaya_mission.gps_loss_decision.decide_gps_loss_response`, `papaya_mission.exclusion_check.find_intruded_exclusion`, `papaya_mission.exclusion_decision.decide_exclusion_response`, `papaya_mission.obstacle_detection.{obstacle_from_ultrasonic_camera_detection, obstacle_from_bump_contact}`, `papaya_mission.classification.classify_permanence` (called internally by `obstacle_from_ultrasonic_camera_detection`, not directly here), `papaya_mission.resume_validation.reconcile_obstacles`, `papaya_mission.local_store.save_obstacle` (the known-obstacle set reconciliation runs against was snapshotted into `._resume_validation_known_rows` back in Task 6, so this task issues no fresh `list_obstacles_for_session` query), `papaya_mission.runtime_config.{GPS_LOSS_GRACE_PERIOD_S, GPS_LOSS_MAX_ERROR_RADIUS_M}`.
- Produces: `.tick() -> None` — one iteration of the sensing/position/obstacle/resume-validation/exclusion sequence (command handling and telemetry are Task 8). Also produces `.mission_alert: str | None` — set to `"gps_stop_and_alert"` or `"exclusion_wait_for_help"` when either decision function returns its stop branch. A resume-validation match distance of 3.0m (matching `resume_validation.reconcile_obstacles`'s own default `match_radius_m`) is used to decide the rover has "arrived" at `._resume_validation_target`.

> **Corrections applied in the final fix wave** (see
> `.superpowers/sdd/2026-09-25-mp1-mission-runtime/final-fix-wave-report.md`).
> Three things in this task as originally specified were wrong or incomplete:
>
> 1. **`mission_alert` lifecycle.** This section said "Task 8's command
>    handling clears it on an operator response" — no such clearing was ever
>    implemented, in Task 8 or anywhere else, so the alert latched for the life
>    of the process even after the condition resolved, and it was never logged
>    or reported either. Each of the two checks now re-evaluates fresh every
>    tick (which is how both decision functions already worked) and clears
>    *its own* alert when its condition genuinely resolves, logging on the
>    transition in and out rather than at tick rate. GPS-loss takes precedence
>    over an exclusion alert: with an untrusted position the intrusion verdict
>    is itself untrustworthy, so an exclusion check must neither clear nor
>    overwrite a held GPS alert. `mission_alert` is also now reported in
>    telemetry (as `"none"` when unset — distinct from the `"missing"`
>    sentinel, which means "could not be read").
> 2. **GPS-loss safety when GPS was never acquired.** `_check_gps_loss`
>    returned immediately while `._last_gps_fix_monotonic` was `None`, and
>    `_read_position`'s dummy-seed path (no real fix ever received) left it
>    `None`. A cold boot under tree cover with zero real fixes therefore never
>    evaluated GPS-loss safety at all. The dummy seed now starts the same
>    grace-period clock: "never had a fix" is treated as "just lost one".
> 3. **Sensor/ESP32 read fault isolation.** `_read_position`,
>    `_detect_obstacles` and the bump poll called injected driver methods
>    unguarded. Each call site is now individually wrapped in
>    `try/except Exception` with a documented degradation per site, and
>    `tick()` skips the position-dependent steps (but still samples telemetry
>    and polls commands) when a failed IMU read leaves no position estimate.
>    The `SHOULD`-not-raise expectation is now written into the `sensor_hub`
>    and `esp32_link` Protocol docstrings.

**Design note on resume-validation's place in the tick sequence:** `._check_resume_validation_arrival()` is a tick step in its own right, called unconditionally right after `._detect_obstacles()` — *not* a call made from inside the paired-detection branch. Two things follow from that, and both are load-bearing:

1. **Arrival is checked whether or not anything was detected.** The reason resume-validation exists is to report that a previously-known obstacle is no longer there, which by definition means arriving at the target and detecting nothing. Driving reconciliation off a detection would make that case unreachable — no detection, no call site, no reconciliation, and the pass stays armed forever.
2. **While a pass is armed, a fresh paired detection is deferred, not saved.** `_detect_obstacles` collects it into `._resume_validation_collected` instead of calling `_save_obstacle` on it. Reconciliation then decides its identity exactly once: a `confirmed` match upserts under the known obstacle's existing id; an unmatched entry in `result.new_detections` saves with a fresh id. Saving on detection *and* reconciling afterwards writes two rows for one physical obstacle — the fresh-id row plus the reused-id upsert — which then both sync to the backend as separate documents, and on the *next* resume pass the orphan fails to match and is reported as a false "this obstacle vanished" discrepancy.

Bump-contact obstacles are outside all of this: they are a reactive source, not a resume-validation input, and keep saving immediately. That is also why the known-obstacle snapshot taken in Task 6 is still load-bearing — bump rows written during the pass are exactly what a live `list_obstacles_for_session` at reconciliation time would wrongly admit into the known set.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_runtime_tick_sensing.py -v`
Expected: FAIL — `AttributeError: 'MissionRuntime' object has no attribute 'tick'` for the first five; the three resume-validation tests fail on the duplicate row / never-reconciled assertions.

- [ ] **Step 3: Add `tick()` and its helpers**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/runtime.py
# Add these imports alongside the existing ones:
import time
from papaya_mission.exclusion_check import find_intruded_exclusion
from papaya_mission.exclusion_decision import decide_exclusion_response
from papaya_mission.gps_loss_decision import decide_gps_loss_response
from papaya_mission.obstacle_detection import (
    obstacle_from_bump_contact,
    obstacle_from_ultrasonic_camera_detection,
)
from papaya_mission.position_fusion import GpsFix, PositionFusion
from papaya_mission.resume_validation import reconcile_obstacles
from papaya_mission.runtime_config import GPS_LOSS_GRACE_PERIOD_S, GPS_LOSS_MAX_ERROR_RADIUS_M

RESUME_VALIDATION_MATCH_RADIUS_M = 3.0

# Add to MissionRuntime.__init__ (alongside the existing attributes):
        self.mission_alert: str | None = None

# Add these methods to MissionRuntime:
    def tick(self) -> None:
        now_monotonic = time.monotonic()
        self._read_position(now_monotonic)
        self._check_gps_loss(now_monotonic)
        self._detect_obstacles()
        self._check_resume_validation_arrival()
        self._check_exclusion_zones()

    def _read_position(self, now_monotonic: float) -> None:
        imu_reading = self.sensor_hub.imu.read()
        gps_fix = self.sensor_hub.gps.read()

        if self.position_fusion is None:
            seed_fix = gps_fix or GpsFix(lat=0.0, lon=0.0, accuracy_m=999.0, timestamp=imu_reading.timestamp)
            self.position_fusion = PositionFusion(seed_fix)
            if gps_fix is not None:
                self._last_gps_fix_monotonic = now_monotonic
            return

        if gps_fix is not None:
            self.position_fusion.on_gps_fix(gps_fix)
            self._last_gps_fix_monotonic = now_monotonic
        else:
            self.position_fusion.on_imu_reading(imu_reading)

    def _check_gps_loss(self, now_monotonic: float) -> None:
        if self._last_gps_fix_monotonic is None:
            return
        seconds_since_last_fix = now_monotonic - self._last_gps_fix_monotonic
        response = decide_gps_loss_response(
            seconds_since_last_fix=seconds_since_last_fix,
            current_error_radius_m=self.position_fusion.current_estimate.error_radius_m,
            grace_period_s=GPS_LOSS_GRACE_PERIOD_S,
            max_error_radius_m=GPS_LOSS_MAX_ERROR_RADIUS_M,
        )
        if response == "stop_and_alert":
            self.mission_alert = "gps_stop_and_alert"

    def _detect_obstacles(self) -> None:
        ultrasonic = self.sensor_hub.ultrasonic.read()
        camera = self.sensor_hub.camera.read()
        if ultrasonic is not None and camera is not None:
            classified_type, confidence = camera
            paired_obstacle = obstacle_from_ultrasonic_camera_detection(
                rover_position=self.position_fusion.current_estimate,
                relative_bearing_deg=ultrasonic.relative_bearing_deg,
                range_m=ultrasonic.range_m,
                classified_type=classified_type,
                classification_confidence=confidence,
                detected_at=datetime.now(timezone.utc),
            )
            if self._resume_validation_target is not None:
                # A resume pass is armed -- don't persist yet. Reconciliation
                # (in _check_resume_validation_arrival) decides whether this is
                # a re-detection (reuse the known obstacle's id, one row) or
                # genuinely new (mint a fresh id, one row). Saving here too
                # would create a SECOND row for a re-detection: the fresh-id
                # row written now, plus the reused-id upsert written at
                # reconciliation -- one physical obstacle, two records, both
                # synced to the backend, and on the next resume pass the
                # orphan fails to match and is reported as a bogus "vanished"
                # discrepancy.
                self._resume_validation_collected.append(paired_obstacle)
            else:
                self._save_obstacle(paired_obstacle)

        # Bump contacts are a separate, reactive obstacle source -- kept
        # independent of the ultrasonic+camera branch above (not folded
        # into one shared variable) so a bump event can never overwrite
        # or double-save a same-tick ultrasonic+camera detection.
        for bump_event in self.esp32_link.poll_bump_events():
            bump_obstacle = obstacle_from_bump_contact(
                rover_position=self.position_fusion.current_estimate,
                detected_at=bump_event.detected_at,
            )
            self._save_obstacle(bump_obstacle)

    def _check_resume_validation_arrival(self) -> None:
        """Reconcile this resume pass's collected detections against the known
        obstacles, once the rover is back at the resume-validation target.

        A tick step in its own right, called unconditionally -- deliberately
        NOT driven off a detection happening. Arriving at the target having
        detected nothing is the single most important case resume validation
        exists to report: it is what turns a pre-crash obstacle that is no
        longer there into a `cleared`/`discrepancies` entry. Hanging this off
        _detect_obstacles' paired-detection branch made that case unreachable,
        because with nothing detected there was no call site to reach it from.
        """
        if self._resume_validation_target is None:
            return

        from papaya_mission.geo_utils import flat_earth_distance_m

        estimate = self.position_fusion.current_estimate
        current_position = (estimate.lon, estimate.lat)
        distance_to_target = flat_earth_distance_m(current_position, self._resume_validation_target)
        if distance_to_target > RESUME_VALIDATION_MATCH_RADIUS_M:
            return  # still transiting back -- keep collecting, reconcile on arrival

        # The known set is the snapshot taken when resume-validation was armed
        # in _resume_in_progress_session_if_any (Task 6): the obstacles stored
        # BEFORE this resume pass began. It is deliberately not re-queried
        # here. Paired detections made during an armed pass are deferred rather
        # than saved, but bump contacts are NOT -- they are a reactive source
        # outside reconciliation and still persist the moment they happen, at
        # the rover's own position. A live list_obstacles_for_session call would
        # therefore hand those bump rows to reconcile_obstacles as "known"
        # obstacles, sitting within metres of this pass's fresh detections; its
        # greedy nearest-first matching would let a bump row claim a fresh
        # detection and crowd out the pre-existing obstacle that detection
        # should have been matched against -- wrongly reporting a
        # still-present obstacle as cleared. See the arming site for the full
        # rationale.
        known_rows = self._resume_validation_known_rows
        # A position can legitimately carry more than one row -- two bump
        # contacts logged at the same position estimate, say -- so map each
        # position to the list of ids stored there and let each confirmed
        # entry consume one. A flat position->id dict would collapse those
        # rows onto a single id, refreshing one row twice while leaving the
        # other stale: the same duplicate-row failure this id lookup exists
        # to prevent.
        known_ids_by_position: dict[tuple[float, float], list[str]] = {}
        for row in known_rows:
            known_ids_by_position.setdefault(row["position"], []).append(row["id"])
        known = [self._obstacle_dict_to_domain(row) for row in known_rows]
        result = reconcile_obstacles(
            known_obstacles=known,
            freshly_detected=self._resume_validation_collected,
            now=datetime.now(timezone.utc),
        )
        for confirmed in result.confirmed:
            # A confirmed obstacle is a RE-detection of one we already store a
            # row for, so it must reuse that row's id. That is what makes
            # save_obstacle's upsert-by-id refresh the record in place (and
            # re-flag it unsynced); minting a fresh id here would insert a
            # second row for the same physical obstacle and defeat the upsert
            # entirely.
            #
            # reconcile_obstacles builds each confirmed entry as
            # dataclasses.replace(known, last_confirmed_at=now), which changes
            # only that one field -- so the entry's position is identical to
            # the known obstacle it came from and is a safe key back to that
            # obstacle's stored id.
            self._save_obstacle(
                confirmed, obstacle_id=known_ids_by_position[confirmed.position].pop(0)
            )
        for new_obstacle in result.new_detections:
            # This is where a genuinely-new obstacle detected during the resume
            # pass finally gets persisted -- exactly once, with a fresh id
            # (no obstacle_id, so _save_obstacle mints one).
            #
            # _detect_obstacles deferred it precisely so this decision could be
            # made here: had it been saved on detection, a fresh row would
            # already exist for every entry that reconciliation then classified
            # as `confirmed`, on top of the reused-id upsert -- two rows per
            # re-detected obstacle. Deferring means each collected detection is
            # written once, under whichever id reconciliation says is correct.
            self._save_obstacle(new_obstacle)
        # `cleared` and `discrepancies` are logged for operator review via
        # telemetry/obstacle status -- no further action in v1.
        self._resume_validation_target = None
        self._resume_validation_collected = []
        self._resume_validation_known_rows = []

    @staticmethod
    def _obstacle_dict_to_domain(obstacle_dict: dict[str, Any]):
        from papaya_mission.obstacle import Obstacle

        return Obstacle(
            position=obstacle_dict["position"],
            position_uncertainty_m=obstacle_dict["position_uncertainty_m"],
            type=obstacle_dict["type"],
            classification_confidence=obstacle_dict["classification_confidence"],
            detection_method=obstacle_dict["detection_method"],
            status=obstacle_dict["status"],
            first_detected_at=obstacle_dict["first_detected_at"],
            last_confirmed_at=obstacle_dict["last_confirmed_at"],
        )

    def _save_obstacle(self, obstacle, *, obstacle_id: str | None = None) -> None:
        if self.sweep_session is None:
            # MP-1's obstacle tracking is scoped to sweep sessions: the local
            # store's obstacles.sweep_session_id is NOT NULL, matching the
            # backend's non-optional Obstacle.sweep_session_id. An obstacle
            # met while no session is active -- during transit, or a bump on
            # the way home -- has no session to attach to, so there is no
            # valid row to write and we skip persisting it rather than
            # inserting a null session id the schema rejects.
            #
            # This costs nothing operationally: the rover still reacts to the
            # obstacle through the normal avoidance path on this tick. Only
            # the durable record is skipped, and a durable record outside a
            # sweep session has nowhere to be reported to anyway.
            return

        lon, lat = obstacle.position
        local_store.save_obstacle(
            self.conn,
            {
                # A re-detected obstacle passes the id of the row it already
                # has, so save_obstacle's upsert refreshes that row in place.
                # A genuinely new detection gets a fresh id.
                "id": obstacle_id or str(uuid.uuid4()),
                "sweep_session_id": self.sweep_session.id,
                "position": (lon, lat),
                "position_uncertainty_m": obstacle.position_uncertainty_m,
                "type": obstacle.type,
                "classification_confidence": obstacle.classification_confidence,
                "detection_method": obstacle.detection_method,
                "status": obstacle.status,
                "first_detected_at": obstacle.first_detected_at,
                "last_confirmed_at": obstacle.last_confirmed_at,
            },
        )

    def _check_exclusion_zones(self) -> None:
        if not self.exclusion_polygons or self.rover is None:
            return
        estimate = self.position_fusion.current_estimate
        position = (estimate.lon, estimate.lat)
        intrusion = find_intruded_exclusion(position, self.exclusion_polygons)
        if intrusion is None:
            return
        _exclusion, depth_m = intrusion
        rover_length_m = self.rover.get("length_m")
        if rover_length_m is None:
            return
        response = decide_exclusion_response(depth_m, rover_length_m)
        if response == "wait_for_help":
            self.mission_alert = "exclusion_wait_for_help"
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_runtime_tick_sensing.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Run the full test suite for regressions**

Run: `pytest -v`
Expected: PASS (all tests from Tasks 1–7)

- [ ] **Step 6: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/runtime.py pathfinder-autonomous/pi-mission/tests/test_runtime_tick_sensing.py
git commit -m "feat(pi-mission): add tick loop position/obstacle/exclusion sensing"
```

---

### Task 8: Command handling, telemetry cadence, and waypoint progress

**Files:**
- Modify: `pathfinder-autonomous/pi-mission/papaya_mission/runtime.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_runtime_tick_commands.py`

**Interfaces:**
- Consumes: `papaya_mission.backend_client.{poll_commands, ack_command}` (Task 4), `papaya_mission.telemetry_record.build_telemetry_record`, `papaya_mission.local_store.{save_telemetry_record, commit, should_commit_telemetry, DEFAULT_TELEMETRY_COMMIT_INTERVAL_S}`, `papaya_mission.sweep_session.SweepSession.{mark_waypoint_complete, interrupt, resume}`, `papaya_mission.esp32_link.Esp32Status`.
- Produces: extends `.tick()` to also handle waypoint-completion, telemetry sampling/commit, and command polling. New command types handled: `start_sweep` → `handle_start_sweep(command["payload"])` (see the final-fix-wave note below); `pause_sweep` → `SweepSession.interrupt()`; `resume_sweep` → `SweepSession.resume()`, and if the ESP32 link was down during the pause, checks `Esp32Link.status()` first — if halted-on-contact, treats it as a bump event instead of resuming (per design notes: Error handling — "ESP32 link reconnects"); `stop_sweep`/`abort_home` → **interrupts** an in-progress session (it never marks one completed — completion happens only via the waypoint-arrival full-coverage path in `_check_waypoint_arrival`) and then calls `_home_return_sync()` directly; `update_geofence` → re-fetches exclusion zones only (not the inclusive boundary/pattern — re-planning a coverage pattern mid-sweep is out of scope for MP-1; this only updates which zones the running `exclusion_check` avoids). Any unrecognized command type falls to an `else` that logs a warning.

> **Corrections applied in the final fix wave** (see
> `.superpowers/sdd/2026-09-25-mp1-mission-runtime/final-fix-wave-report.md`).
> This section originally described a `._pending_sync = True` flag for Task 9
> to pick up; that flag was never implemented and was superseded by the
> direct `_home_return_sync()` call above. It also said `stop_sweep`/
> `abort_home` "marks the session interrupted/completed as appropriate",
> which overstated it — that path only ever interrupts. Separately, the
> `start_sweep` branch was missing from the implemented `_handle_command`
> entirely (`handle_start_sweep` existed and was only ever called directly by
> tests), so a `start_sweep` polled from the backend was silently acked
> without starting anything; it is now dispatched, and the per-command guard
> catches `Exception` rather than only `httpx.HTTPError` so a malformed
> command cannot take down the tick.
>
> The telemetry sample this task produces was also hollow: `readings` only
> ever held `error_radius_m`/`heading_deg`, which (see the Task 5 correction)
> never intersected `expected_metrics`, so every stored record was
> all-`"missing"` and `position` — the design spec's primary live-summary
> metric — was never emitted. `_sample_telemetry_if_due` now populates
> `position` (GeoJSON `[lon, lat]`), `position_uncertainty_m`,
> `error_radius_m`, `heading_deg`, `nav_mode`
> (`idle`/`sweeping`/`interrupted`), `waypoint_index`, `mission_alert`, and —
> new in this wave, human-approved — `throttle_position` plus per-servo
> `servo_{id}_deg` keys read from a new `Esp32Link.read_drive_status()`
> returning a `DriveStatus` dataclass. Those per-servo keys are dynamic, so
> they cannot live in the static `MP1_EXPECTED_METRICS`;
> `_sample_telemetry_if_due` extends the expected set with that sample's real
> servo ids before calling `build_telemetry_record`, leaving that function's
> already-tested floor-and-ceiling contract untouched. The `DriveStatus`
> servo key names are a placeholder pending the ESP32 firmware plan settling
> the real steering-servo naming convention.

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_runtime_tick_commands.py
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


# Added post-review: the Global Constraints require that a failure
# polling/acking commands never stops the mission. Two tests proving
# that fault isolation, matching the httpx.MockTransport error-response
# pattern already used above.
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
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_runtime_tick_commands.py -v`
Expected: FAIL — pause/resume don't change `sweep_session.status` yet, no telemetry saved, waypoints never marked complete.

- [ ] **Step 3: Extend `tick()` and add the command/telemetry/waypoint helpers**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/runtime.py
# backend_client is already imported (Task 5's `from papaya_mission
# import backend_client, local_store`) -- add these new imports
# alongside the existing ones:
from papaya_mission.local_store import (
    DEFAULT_TELEMETRY_COMMIT_INTERVAL_S,
    commit as local_store_commit,
    save_telemetry_record,
    should_commit_telemetry,
)
from papaya_mission.runtime_config import COMMAND_POLL_INTERVAL_S, TELEMETRY_SAMPLE_INTERVAL_S
from papaya_mission.telemetry_record import build_telemetry_record

# Also add near the top of the module, if not already present (the
# Global Constraints' fault-isolation rule applies here: a failure
# polling/acking commands must never stop the mission):
import logging
logger = logging.getLogger("papaya_mission.runtime")

WAYPOINT_ARRIVAL_RADIUS_M = 1.0

# Replace MissionRuntime.tick() with:
    def tick(self) -> None:
        now_monotonic = time.monotonic()
        self._read_position(now_monotonic)
        self._check_gps_loss(now_monotonic)
        self._detect_obstacles()
        self._check_resume_validation_arrival()
        self._check_exclusion_zones()
        self._check_waypoint_arrival()
        self._sample_telemetry_if_due(now_monotonic)
        self._poll_and_handle_commands_if_due(now_monotonic)

# Add these methods to MissionRuntime:
    def _check_waypoint_arrival(self) -> None:
        if self.sweep_session is None or self.sweep_session.status != SweepSessionStatus.IN_PROGRESS:
            return
        remaining = self.sweep_session.remaining_waypoints
        if not remaining:
            return
        next_waypoint = remaining[0]

        from papaya_mission.geo_utils import flat_earth_distance_m
        estimate = self.position_fusion.current_estimate
        distance = flat_earth_distance_m((estimate.lon, estimate.lat), next_waypoint.position)
        if distance <= WAYPOINT_ARRIVAL_RADIUS_M:
            self.sweep_session.mark_waypoint_complete(next_waypoint.order)
            self._save_sweep_session()

    def _sample_telemetry_if_due(self, now_monotonic: float) -> None:
        if now_monotonic - self._last_telemetry_sample_monotonic < TELEMETRY_SAMPLE_INTERVAL_S:
            return
        self._last_telemetry_sample_monotonic = now_monotonic
        self._telemetry_sequence_number += 1

        estimate = self.position_fusion.current_estimate if self.position_fusion else None
        readings = {}
        if estimate is not None:
            readings["error_radius_m"] = estimate.error_radius_m
            readings["heading_deg"] = estimate.heading_deg

        record = build_telemetry_record(
            record_id=str(uuid.uuid4()),
            rover_id=self.rover_id,
            timestamp=datetime.now(timezone.utc),
            local_tz_offset_minutes=_local_tz_offset_minutes(),
            sequence_number=self._telemetry_sequence_number,
            readings=readings,
            expected_metrics=self.expected_metrics,
            sweep_session_id=self.sweep_session.id if self.sweep_session else None,
        )
        save_telemetry_record(self.conn, record)

        now = datetime.now(timezone.utc)
        if should_commit_telemetry(self._last_telemetry_commit_at, now, DEFAULT_TELEMETRY_COMMIT_INTERVAL_S):
            local_store_commit(self.conn)
            self._last_telemetry_commit_at = now

    def _poll_and_handle_commands_if_due(self, now_monotonic: float) -> None:
        if now_monotonic - self._last_command_poll_monotonic < COMMAND_POLL_INTERVAL_S:
            return
        self._last_command_poll_monotonic = now_monotonic

        # Global Constraints: "a failure ... polling commands ... must
        # never stop the mission -- log it, treat it as a momentary
        # 'missing' reading for that tick, and continue." The cadence gate
        # above already ran and updated the monotonic sentinel BEFORE this
        # try block, so a failure here naturally retries next interval
        # with no extra bookkeeping.
        try:
            commands = backend_client.poll_commands(self.http_client, self.backend_base_url, self.rover_id)
        except httpx.HTTPError:
            logger.warning("command poll failed -- will retry next interval", exc_info=True)
            return

        for command in commands:
            # Wrapped per-command, inside the loop: one command's ack
            # failure must not prevent the rest of the batch from being
            # handled this tick.
            try:
                self._handle_command(command)
                backend_client.ack_command(self.http_client, self.backend_base_url, command["_id"])
            except httpx.HTTPError:
                logger.warning(
                    "failed to handle/ack command %s -- will retry next poll",
                    command.get("_id"), exc_info=True,
                )

    def _handle_command(self, command: dict[str, Any]) -> None:
        command_type = command["type"]
        if command_type == "pause_sweep":
            if self.sweep_session is not None:
                self.sweep_session.interrupt(datetime.now(timezone.utc))
                self._save_sweep_session()
        elif command_type == "resume_sweep":
            self._handle_resume_sweep()
        elif command_type in ("stop_sweep", "abort_home"):
            if self.sweep_session is not None and self.sweep_session.status == SweepSessionStatus.IN_PROGRESS:
                self.sweep_session.interrupt(datetime.now(timezone.utc))
                self._save_sweep_session()
        elif command_type == "update_geofence":
            all_geofences = backend_client.list_geofences(self.http_client, self.backend_base_url)
            self.exclusion_polygons = [
                shape(g["boundary"]) for g in all_geofences if g["type"] == "exclusive"
            ]

    def _handle_resume_sweep(self) -> None:
        status = self.esp32_link.status()
        if status.halted_on_contact:
            # A bump occurred while the link was down (or since the last
            # check) -- treat it like any other bump event rather than
            # blindly resuming movement. See design notes: Error handling.
            obstacle = obstacle_from_bump_contact(
                rover_position=self.position_fusion.current_estimate,
                detected_at=datetime.now(timezone.utc),
            )
            self._save_obstacle(obstacle)
            return
        if self.sweep_session is not None and self.sweep_session.status == SweepSessionStatus.INTERRUPTED:
            self.sweep_session.resume()
            self._save_sweep_session()


def _local_tz_offset_minutes() -> int:
    offset = datetime.now().astimezone().utcoffset()
    return int(offset.total_seconds() // 60) if offset is not None else 0
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_runtime_tick_commands.py -v`
Expected: PASS (7 passed -- 5 from the original TDD pass plus the two
fault-isolation tests added post-review)

- [ ] **Step 5: Run the full test suite for regressions**

Run: `pytest -v`
Expected: PASS (all tests from Tasks 1–8)

- [ ] **Step 6: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/runtime.py pathfinder-autonomous/pi-mission/tests/test_runtime_tick_commands.py
git commit -m "feat(pi-mission): add command handling, telemetry cadence, and waypoint progress"
```

---

### Task 9: Home-return sync, CLI entrypoint, and integration test

**Files:**
- Modify: `pathfinder-autonomous/pi-mission/papaya_mission/runtime.py`
- Create: `pathfinder-autonomous/pi-mission/__main__.py`
- Create: `pathfinder-autonomous/pi-mission/tests/test_runtime_sync_and_integration.py`
- Modify: `pathfinder-autonomous/pi-mission/README.md`

**Interfaces:**
- Consumes: `papaya_mission.sync_client.sync_all` (Pi Local Store & Sync Client plan), everything from Tasks 1–8.
- Produces: extends `.tick()`'s `stop_sweep`/`abort_home` and waypoint-completion-to-full-coverage paths to call `sync_client.sync_all(self.conn, self.http_client, self.backend_base_url)` at the Home-return checkpoint. `__main__.py`: a CLI entrypoint that loads `RuntimeSettings`, constructs a `MissionRuntime` (using `SimulatedSensorHub`/a fake `Esp32Link` for now — real hardware drivers are a future hardware-integration pass, per design notes), and runs the tick loop at `TICK_INTERVAL_S` forever, logging per-tick duration (the scaling-note trigger).

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_runtime_sync_and_integration.py
from datetime import datetime, timezone

import httpx

from papaya_mission.esp32_link import FakeEsp32Link
from papaya_mission.position_fusion import GpsFix, ImuReading
from papaya_mission.runtime import MissionRuntime
from papaya_mission.sensor_hub import SimulatedSensorHub
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
    runtime.tick()  # seed position
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


# Added post-review: proves the Home-return sync's fault isolation
# (design spec's Error handling table: "Backend unreachable (command
# poll, sync) -> Log, retry next interval. Never blocks the tick
# loop."). The local interrupt and the sync attempt are independent --
# a failed sync must not undo the local state change.
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
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_runtime_sync_and_integration.py -v`
Expected: FAIL — `stop_sweep`/`abort_home` don't sync yet.

- [ ] **Step 3: Wire Home-return sync into `_handle_command`**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/runtime.py
# Add this import alongside the existing ones:
from papaya_mission import sync_client

# Replace the stop_sweep/abort_home branch inside _handle_command with:
        elif command_type in ("stop_sweep", "abort_home"):
            if self.sweep_session is not None and self.sweep_session.status == SweepSessionStatus.IN_PROGRESS:
                self.sweep_session.interrupt(datetime.now(timezone.utc))
                self._save_sweep_session()
            self._home_return_sync()

# Add this method to MissionRuntime:
    def _home_return_sync(self) -> None:
        # Design spec Error handling table: "Backend unreachable (command
        # poll, sync) -> Log, retry next interval. Never blocks the tick
        # loop." A failed sync leaves the records unsynced -- they are
        # picked up again by the next Home-return sync or the next
        # startup's resume path -- rather than crashing the process.
        try:
            sync_client.sync_all(self.conn, self.http_client, self.backend_base_url)
        except httpx.HTTPError:
            logger.warning(
                "Home-return sync failed -- records remain unsynced for the next attempt",
                exc_info=True,
            )
```

Also add the same `_home_return_sync()` call at the end of
`_check_waypoint_arrival()` when the sweep session becomes fully
covered — mission completion is the other Home-return trigger besides
an operator's `stop_sweep`/`abort_home`:

```python
    def _check_waypoint_arrival(self) -> None:
        if self.sweep_session is None or self.sweep_session.status != SweepSessionStatus.IN_PROGRESS:
            return
        remaining = self.sweep_session.remaining_waypoints
        if not remaining:
            return
        next_waypoint = remaining[0]

        from papaya_mission.geo_utils import flat_earth_distance_m
        estimate = self.position_fusion.current_estimate
        distance = flat_earth_distance_m((estimate.lon, estimate.lat), next_waypoint.position)
        if distance <= WAYPOINT_ARRIVAL_RADIUS_M:
            self.sweep_session.mark_waypoint_complete(next_waypoint.order)
            self._save_sweep_session()
            if self.sweep_session.is_fully_covered:
                self.sweep_session.complete(datetime.now(timezone.utc))
                self._save_sweep_session()
                self._home_return_sync()
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_runtime_sync_and_integration.py -v`
Expected: PASS (3 passed -- 2 from the original TDD pass plus the
Home-return sync fault-isolation test added post-review)

- [ ] **Step 5: Write the CLI entrypoint**

```python
# pathfinder-autonomous/pi-mission/__main__.py
"""CLI entrypoint for the Mission Runtime. Wires MissionRuntime with
SimulatedSensorHub / a placeholder Esp32Link until real hardware
drivers exist (future hardware-integration pass -- see design notes'
Architecture & file structure)."""
from __future__ import annotations

import logging
import time

from papaya_mission.esp32_link import FakeEsp32Link
from papaya_mission.position_fusion import ImuReading
from papaya_mission.runtime import MissionRuntime
from papaya_mission.runtime_config import TICK_INTERVAL_S, load_runtime_settings
from papaya_mission.sensor_hub import SimulatedSensorHub

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("papaya_mission.runtime")


def main() -> None:
    settings = load_runtime_settings()
    sensor_hub = SimulatedSensorHub(
        ImuReading(heading_deg=0.0, forward_acceleration_mps2=0.0, timestamp=time.monotonic())
    )
    esp32_link = FakeEsp32Link()

    runtime = MissionRuntime(
        rover_id=settings.rover_id,
        backend_base_url=settings.backend_base_url,
        local_db_path=settings.local_db_path,
        sensor_hub=sensor_hub,
        esp32_link=esp32_link,
    )
    runtime.startup()
    logger.info("Mission Runtime started for rover %s", settings.rover_id)

    while True:
        tick_started = time.monotonic()
        runtime.tick()
        tick_duration_s = time.monotonic() - tick_started
        if tick_duration_s > TICK_INTERVAL_S:
            logger.warning(
                "tick took %.3fs, over the %.3fs budget (TICK_HZ) -- see design notes' Scaling note",
                tick_duration_s, TICK_INTERVAL_S,
            )
        time.sleep(max(0.0, TICK_INTERVAL_S - tick_duration_s))


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run the full test suite for regressions**

Run: `pytest -v`
Expected: PASS (all tests from Tasks 1–9)

- [ ] **Step 7: Update the README**

Add a new section to `pathfinder-autonomous/pi-mission/README.md` (create it if it doesn't exist yet from the prior four plans):

```markdown
## Mission Runtime

`python -m papaya_mission` runs the mission loop. Requires `.env` with
`ROVER_ID`, `BACKEND_BASE_URL` (the running Backend Core service), and
`LOCAL_DB_PATH` (SQLite file path — created if absent).

Currently wired to `SimulatedSensorHub` and a fake `Esp32Link` — real
hardware drivers (GPS/IMU/ultrasonic/camera modules, the actual
UART/I2C link to the ESP32) are a future hardware-integration pass, not
part of this plan. `runtime.py`'s `MissionRuntime` takes both as
constructor arguments specifically so real drivers can be swapped in
later without touching orchestration logic.

Per-tick duration is logged; a warning means a tick exceeded its
`TICK_HZ` budget — see the MP-1 Mission Runtime design notes' "Scaling
note" for what that means and what to do about it.
```

- [ ] **Step 8: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/runtime.py pathfinder-autonomous/pi-mission/__main__.py pathfinder-autonomous/pi-mission/tests/test_runtime_sync_and_integration.py pathfinder-autonomous/pi-mission/README.md
git commit -m "feat(pi-mission): add Home-return sync, CLI entrypoint, and end-to-end test"
```

---

## Self-Review Notes

- **Spec coverage:** Execution model (single-threaded tick loop) ✓ Task 7/8. Pi↔ESP32 interface defined now, firmware deferred ✓ Task 3. Thin-orchestrator structure ✓ all runtime.py tasks call into already-tested modules, no new business logic. Crash/power-loss auto-resume ✓ Task 6. Loop timing constants ✓ Task 1. Bump-sensor safety ownership (ESP32 autonomous, link-loss is not a safety event) ✓ Task 8's `_handle_resume_sweep`. Mission lifecycle (startup/idle/start_sweep/tick/Home-return) ✓ Tasks 5, 8, 9. Error handling table (sensor failures log-and-continue, GPS loss/IMU failure route through `gps_loss_decision`, backend/SQLite failures non-fatal) — sensor read failures naturally become `None`/no-op through the `SensorHub`/`Esp32Link` Protocol contracts rather than needing explicit try/except in this plan's own code, since a real driver's I/O exceptions are a hardware-integration-pass concern, not this plan's; GPS/IMU loss ✓ Task 7. Testing strategy (fakes for hardware/network boundaries, real pure-logic modules) ✓ every task's tests.
- **Placeholder scan:** `SENSOR_DETECTION_WIDTH_M`'s value is explicitly flagged as a placeholder pending hardware selection (an already-known open item from the MP-1 design spec's BOM, not a plan gap) — every other value is a real, reasoned default. No TBD/TODO.
- **Type consistency:** `MissionRuntime.sweep_session: SweepSession | None` used consistently from Task 5 onward. `.exclusion_polygons: list[Polygon]` (shapely) consistent across Tasks 5, 6, 7, 8. Obstacle dicts passed to `local_store.save_obstacle` match the exact shape `local_store.py` (Pi Local Store & Sync Client plan) expects, including the `sweep_session_id` key that `papaya_mission.obstacle.Obstacle` itself doesn't carry (added by `MissionRuntime._save_obstacle`, not invented ad hoc per call site). `SweepSession.pattern`'s wire-format conversion (`Waypoint` → `{"order", "position": {"type": "Point", "coordinates": [...]}}`) is centralized in `_save_sweep_session`, used identically by Tasks 5, 6, 8, 9 rather than reimplemented per call site.
