# StatusDisplay / Runtime State Gap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `MissionRuntime` expose the live state `StatusDisplay`'s screens already assume (a `readings` snapshot, an obstacle counter, and `halted_on_contact`), so the two components actually connect — today `StatusDisplay` cannot be wired to a real `MissionRuntime` without crashing or showing permanently-empty screens.

**Architecture:** All changes are additive to `papaya_mission/runtime.py` (and its tests). `status_display.py` itself needs **no changes** — its renderers were already written against exactly this state shape (`state.get("position")`, `state.get("obstacle_count", 0)`, etc.); the gap was entirely on the producing side. A new `MissionRuntime.last_telemetry_readings` attribute holds a live snapshot of the pre-sentinel `readings` dict that `_sample_telemetry_if_due` already builds every sample; a new in-memory obstacle counter is threaded through `_save_obstacle`/`handle_start_sweep`.

**Tech Stack:** Python 3.12, pytest. No new dependencies. Reuses existing `Esp32Status` (`esp32_link.py`), `DEFAULT_SCREENS`/`StatusDisplay` (`status_display.py`, unchanged), and the existing `_make_started_runtime`/`FakeEsp32Link`/`SimulatedSensorHub` test fixtures already used across `tests/test_runtime_*.py`.

## Global Constraints

- **Local/live only — do not touch the sync contract.** `obstacle_count`, `last_obstacle_type`, and `halted_on_contact` must NOT be added to `MP1_EXPECTED_METRICS` (`runtime_config.py`) and must not appear in any `build_telemetry_record`/`save_telemetry_record`/backend-sync call. They live only in the new `self.last_telemetry_readings` live snapshot. Adding them to the synced telemetry package is an explicitly deferred follow-up, not part of this plan.
- **`status_display.py` is not modified by this plan.** Its renderers already expect exactly the state shape this plan produces — do not add defensive code there to compensate for a producer-side gap.
- **Obstacle counter counts every detection, not just persisted ones.** `_save_obstacle()` currently returns early (without writing a row) when `self.sweep_session is None`. The counter increments regardless of that early return.
- **Obstacle counter resets per sweep session**, zeroed in `handle_start_sweep()` — it reports "this mission," not a lifetime total.
- Design spec: `docs/superpowers/specs/2026-10-01-status-display-runtime-gap-design.md`.

---

## File Structure

```
pathfinder-autonomous/pi-mission/
  papaya_mission/
    runtime.py              # MODIFY -- new state + _sample_telemetry_if_due
                             #           + _save_obstacle + handle_start_sweep
  tests/
    test_runtime_tick_sensing.py   # MODIFY -- append new tests (Tasks 1 & 2)
    test_runtime_startup.py        # MODIFY -- append one new test (Task 2)
    test_status_display_integration.py  # NEW -- Task 3
```

---

### Task 1: Expose a live telemetry-readings snapshot, with `halted_on_contact`

**Files:**
- Modify: `pathfinder-autonomous/pi-mission/papaya_mission/runtime.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_runtime_tick_sensing.py`

**Interfaces:**
- Consumes: `papaya_mission.esp32_link.Esp32Status` (unchanged, existing: field `halted_on_contact: bool`), `self.esp32_link.status() -> Esp32Status` (unchanged, existing method already used elsewhere in this file).
- Produces: `MissionRuntime.last_telemetry_readings: dict[str, Any]` — present on every instance from `__init__` onward (starts as `{}`), replaced with the latest fully-assembled `readings` dict every time `_sample_telemetry_if_due` actually samples (i.e. once per `TELEMETRY_SAMPLE_INTERVAL_S`, same cadence as the persisted telemetry record). Task 2 extends the same `readings` dict earlier in this method with two more keys before this snapshot is taken; Task 3 reads `runtime.last_telemetry_readings` directly.

- [ ] **Step 1: Write the failing tests**

Append to `pathfinder-autonomous/pi-mission/tests/test_runtime_tick_sensing.py` (it already imports `FakeEsp32Link`, `GpsFix`, `ImuReading`, `SimulatedSensorHub`, `MissionRuntime`, and defines `_make_started_runtime`/`INITIAL_IMU` — reuse them, do not redefine):

```python
from papaya_mission.esp32_link import Esp32Status


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
```

- [ ] **Step 2: Run the tests and verify they fail**

Run (from `pathfinder-autonomous/pi-mission/`): `pytest tests/test_runtime_tick_sensing.py -k "last_telemetry_readings or halted_on_contact" -v`
Expected: FAIL — `AttributeError: 'MissionRuntime' object has no attribute 'last_telemetry_readings'`

- [ ] **Step 3: Write the implementation**

In `papaya_mission/runtime.py`, in `__init__`, find this exact existing line (currently the last line of `__init__`):

```python
        self.mission_alert: str | None = None
```

Add immediately after it:

```python
        self.mission_alert: str | None = None
        # Live, pre-sentinel snapshot of the latest telemetry sample, for any
        # in-process consumer (e.g. StatusDisplay) that needs current state
        # right now rather than through the persisted/synced copy -- see
        # _sample_telemetry_if_due. build_telemetry_record's "missing"
        # substitution and expected_metrics filtering apply only to that
        # persisted copy, never to this one.
        self.last_telemetry_readings: dict[str, Any] = {}
```

In `_sample_telemetry_if_due`, find this exact existing block:

```python
        if drive_status is not None:
            readings["throttle_position"] = drive_status.throttle_position
            for servo_id, angle_deg in drive_status.servo_positions_deg.items():
                readings[f"servo_{servo_id}_deg"] = angle_deg
        # Per-servo keys are dynamic (`servo_{id}_deg`, from whatever ids the
        # ESP32 reported THIS tick), so they cannot be pre-enumerated in the
        # static MP1_EXPECTED_METRICS -- and build_telemetry_record drops any
        # reading outside the expected set. Extend the set for this one sample
        # instead of changing that function: its floor-and-ceiling contract is
        # already established and tested by two earlier plans.
        expected_metrics_this_sample = self.expected_metrics | {
```

Insert between the `if drive_status is not None:` block and the `# Per-servo keys are dynamic` comment:

```python
        if drive_status is not None:
            readings["throttle_position"] = drive_status.throttle_position
            for servo_id, angle_deg in drive_status.servo_positions_deg.items():
                readings[f"servo_{servo_id}_deg"] = angle_deg

        try:
            halted_on_contact = self.esp32_link.status().halted_on_contact
        except Exception:
            # Same rationale as the read_drive_status handling above: leave
            # this one field out of the sample rather than assert a
            # not-halted state we were not actually able to confirm.
            logger.warning(
                "ESP32 status read failed -- leaving halted_on_contact out of this sample",
                exc_info=True,
            )
            halted_on_contact = None
        if halted_on_contact is not None:
            readings["halted_on_contact"] = halted_on_contact

        # Snapshot the fully-assembled, pre-sentinel readings for any live
        # consumer. Deliberately the SAME dict object build_telemetry_record
        # reads below, not a copy -- any keys Task 2 adds earlier in this
        # method are already present in it by this point.
        self.last_telemetry_readings = readings

        # Per-servo keys are dynamic (`servo_{id}_deg`, from whatever ids the
        # ESP32 reported THIS tick), so they cannot be pre-enumerated in the
        # static MP1_EXPECTED_METRICS -- and build_telemetry_record drops any
        # reading outside the expected set. Extend the set for this one sample
        # instead of changing that function: its floor-and-ceiling contract is
        # already established and tested by two earlier plans.
        expected_metrics_this_sample = self.expected_metrics | {
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_runtime_tick_sensing.py -v`
Expected: PASS (all tests in the file, including the 4 new ones)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/runtime.py pathfinder-autonomous/pi-mission/tests/test_runtime_tick_sensing.py
git commit -m "feat(pi-mission): expose a live telemetry-readings snapshot with halted_on_contact"
```

---

### Task 2: Obstacle counter (`obstacle_count` / `last_obstacle_type`)

**Files:**
- Modify: `pathfinder-autonomous/pi-mission/papaya_mission/runtime.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_runtime_tick_sensing.py`, `pathfinder-autonomous/pi-mission/tests/test_runtime_startup.py`

**Interfaces:**
- Consumes: `MissionRuntime.last_telemetry_readings` (Task 1, unchanged — this task adds two more keys to the `readings` dict earlier in `_sample_telemetry_if_due`, before Task 1's snapshot line runs, so both land in the same snapshot automatically).
- Produces: `MissionRuntime._obstacle_count: int` and `MissionRuntime._last_obstacle_type: str` (private instance state, reset to `0`/`"-"` by `handle_start_sweep`), and `readings["obstacle_count"]`/`readings["last_obstacle_type"]` inside `_sample_telemetry_if_due`. Task 3 reads these via `runtime.last_telemetry_readings["obstacle_count"]` / `["last_obstacle_type"]`.

- [ ] **Step 1: Write the failing tests**

Append to `pathfinder-autonomous/pi-mission/tests/test_runtime_tick_sensing.py` (reuses `BumpEvent`, already imported at the top of this file):

```python
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
```

Append to `pathfinder-autonomous/pi-mission/tests/test_runtime_startup.py`:

```python
def test_start_sweep_resets_obstacle_count_and_last_type(tmp_path):
    rover = {"_id": "rover-1", "name": "George", "turn_style": "spin_in_place"}
    inclusive = {"_id": "fence-1", "type": "inclusive", "boundary": {"type": "Polygon", "coordinates": [FIELD_RING]}}
    runtime = _make_runtime(tmp_path, rover, geofences=[inclusive])
    runtime.startup()
    runtime.handle_start_sweep({"geofence_id": "fence-1"})
    # Simulate a prior session that had already detected some obstacles.
    runtime._obstacle_count = 5
    runtime._last_obstacle_type = "barrel"

    runtime.handle_start_sweep({"geofence_id": "fence-1"})  # a fresh sweep starts

    assert runtime._obstacle_count == 0
    assert runtime._last_obstacle_type == "-"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_runtime_tick_sensing.py tests/test_runtime_startup.py -k "obstacle_count or last_obstacle_type" -v`
Expected: FAIL — `AttributeError: 'MissionRuntime' object has no attribute '_obstacle_count'`

- [ ] **Step 3: Write the implementation**

In `papaya_mission/runtime.py`'s `__init__`, add alongside the other new state from Task 1 (find the `self.last_telemetry_readings: dict[str, Any] = {}` line Task 1 added, and insert after it):

```python
        self.last_telemetry_readings: dict[str, Any] = {}
        # Live, in-memory counters for the obstacles-screen LCD state. Reset
        # per sweep session (handle_start_sweep) -- these report "this
        # mission", not a lifetime total across a bench day of many short
        # test sweeps.
        self._obstacle_count: int = 0
        self._last_obstacle_type: str = "-"
```

In `_save_obstacle`, find this exact existing method body:

```python
    def _save_obstacle(self, obstacle, *, obstacle_id: str | None = None) -> None:
        if self.sweep_session is None:
```

Change to:

```python
    def _save_obstacle(self, obstacle, *, obstacle_id: str | None = None) -> None:
        # Counted regardless of whether a session exists to persist a row to
        # below -- the rover reacted to this obstacle either way, which is
        # what the live counter reports.
        self._obstacle_count += 1
        self._last_obstacle_type = obstacle.type
        if self.sweep_session is None:
```

In `handle_start_sweep`, find this exact existing line:

```python
    def handle_start_sweep(self, payload: dict[str, Any]) -> None:
        geofence_id = payload["geofence_id"]
```

Change to:

```python
    def handle_start_sweep(self, payload: dict[str, Any]) -> None:
        self._obstacle_count = 0
        self._last_obstacle_type = "-"  # matches _render_obstacles' own default
        geofence_id = payload["geofence_id"]
```

In `_sample_telemetry_if_due`, find this exact existing line:

```python
        readings["mission_alert"] = self.mission_alert or "none"
```

Add immediately after it:

```python
        readings["mission_alert"] = self.mission_alert or "none"
        readings["obstacle_count"] = self._obstacle_count
        readings["last_obstacle_type"] = self._last_obstacle_type
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_runtime_tick_sensing.py tests/test_runtime_startup.py -v`
Expected: PASS (all tests in both files)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/runtime.py pathfinder-autonomous/pi-mission/tests/test_runtime_tick_sensing.py pathfinder-autonomous/pi-mission/tests/test_runtime_startup.py
git commit -m "feat(pi-mission): track a live obstacle_count/last_obstacle_type, reset per sweep session"
```

---

### Task 3: Integration test — `StatusDisplay` against a real `MissionRuntime` tick

**Files:**
- Create: `pathfinder-autonomous/pi-mission/tests/test_status_display_integration.py`

**Interfaces:**
- Consumes: `MissionRuntime.last_telemetry_readings` (Tasks 1-2), `papaya_mission.status_display.{StatusDisplay, DEFAULT_SCREENS}` (unchanged, existing), `papaya_mission.esp32_link.{BumpEvent, Esp32Status, FakeEsp32Link}` (unchanged, existing), `papaya_mission.sensor_hub.SimulatedSensorHub` (unchanged, existing), `papaya_mission.position_fusion.{GpsFix, ImuReading}` (unchanged, existing).
- Produces: nothing consumed by later tasks — this is the final task in the plan.

- [ ] **Step 1: Write the failing test**

```python
# pathfinder-autonomous/pi-mission/tests/test_status_display_integration.py
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
    assert "38.05" in position_line1  # a real fix rendered, not "GPS: no fix"

    obstacles_line1, obstacles_line2 = lcd.writes[2]
    assert obstacles_line1 == "Obstacles: 1"
    assert obstacles_line2 == "Last: unknown"  # obstacle_from_bump_contact's type

    _drive_line1, drive_line2 = lcd.writes[3]
    assert drive_line2 == "HALTED"
```

- [ ] **Step 2: Run the test and verify it fails for the right reason**

Run: `pytest tests/test_status_display_integration.py -v`
Expected: FAIL at this point only if Tasks 1-2 are not yet merged (`AttributeError`/`KeyError` on `last_telemetry_readings`/`obstacle_count`/`halted_on_contact`). If Tasks 1-2 are already merged (the normal case, executing this plan in order), this test should PASS immediately — it adds no new production code, only a test proving Tasks 1-2's work actually connects to `StatusDisplay`. Treat an unexpected failure as a real integration bug to fix, not a step to skip.

- [ ] **Step 3: (No new implementation)**

This task only proves the state Tasks 1-2 added is actually consumable by `StatusDisplay`'s real renderers end-to-end — the same role `test_hardware_drivers_integration.py` played for the hardware drivers plan, and the specific gap that plan's own integration test left open (it never exercised `status_display.py`).

- [ ] **Step 4: Run the full test suite and verify everything passes**

Run: `pytest -v` (from `pathfinder-autonomous/pi-mission/`)
Expected: PASS — all prior tests plus this plan's 7 new tests (4 Task 1 + 2 Task 2 in `test_runtime_tick_sensing.py` + 1 Task 2 in `test_runtime_startup.py` + 1 Task 3 integration test = 8 total; count the real number from your own run rather than forcing it to match).

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/tests/test_status_display_integration.py
git commit -m "test(pi-mission): prove StatusDisplay renders real MissionRuntime state end-to-end"
```
