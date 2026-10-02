# Drive-Screen Halted/Running Ambiguity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `status_display.py`'s drive screen so a failed (or never-yet-attempted) ESP32 status read shows a distinct "unknown" state instead of being indistinguishable from a confirmed "not halted."

**Architecture:** `_render_drive` currently reads `state.get("halted_on_contact", False)`, which cannot tell "key absent" from "key present and `False`." Switch to an explicit `"halted_on_contact" not in state` check, rendering `"LINK?"` for the absent case. This is a single-function fix in `status_display.py` with matching unit and integration test coverage — no other file changes.

**Tech Stack:** Python 3.12, pytest. No new dependencies.

## Global Constraints

- The fix is localized to `_render_drive` in `status_display.py` — no other renderer (`_render_position`, `_render_mission`, `_render_obstacles`) changes.
- No changes to `runtime.py` — `MissionRuntime.last_telemetry_readings` already omits `halted_on_contact` correctly on a failed `esp32_link.status()` read (from the prior runtime-state-gap plan); this plan only changes how the display interprets that omission.
- The unknown-state label is exactly `"LINK?"` (confirmed with the user during brainstorming).
- An explicit `halted_on_contact: False` in the state dict must still render `"running"` — the fix changes how *absence* is handled, not the meaning of a real `False`.
- Design spec: `docs/superpowers/specs/2026-10-01-drive-screen-halted-ambiguity-design.md`.

---

## File Structure

```
pathfinder-autonomous/pi-mission/
  papaya_mission/
    status_display.py                   # MODIFY -- _render_drive only
  tests/
    test_status_display.py              # MODIFY -- append 2 unit tests
    test_status_display_integration.py  # MODIFY -- append 1 integration test
```

---

### Task 1: Distinguish "unknown" from "confirmed not halted" on the drive screen

**Files:**
- Modify: `pathfinder-autonomous/pi-mission/papaya_mission/status_display.py`
- Modify: `pathfinder-autonomous/pi-mission/tests/test_status_display.py`
- Modify: `pathfinder-autonomous/pi-mission/tests/test_status_display_integration.py`

**Interfaces:**
- Consumes: `papaya_mission.status_display.DEFAULT_SCREENS` (unchanged structure — still a 4-element list of `Screen`, `drive` still the 4th); `MissionRuntime.last_telemetry_readings`, `MissionRuntime.esp32_link.status()` (both unchanged, existing, from the prior runtime-state-gap plan).
- Produces: nothing consumed by a later task — this plan has one task.

- [ ] **Step 1: Write the failing unit tests**

Append to `pathfinder-autonomous/pi-mission/tests/test_status_display.py` (it already has a `from papaya_mission.status_display import DEFAULT_SCREENS` import inside an existing test function — add a fresh one per new test, matching that file's existing style):

```python
def test_drive_screen_shows_link_unknown_when_halted_on_contact_is_absent():
    from papaya_mission.status_display import DEFAULT_SCREENS

    drive_screen = next(s for s in DEFAULT_SCREENS if s.name == "drive")

    _line1, line2 = drive_screen.render({})

    assert line2 == "LINK?"


def test_drive_screen_still_shows_running_for_an_explicit_false():
    from papaya_mission.status_display import DEFAULT_SCREENS

    drive_screen = next(s for s in DEFAULT_SCREENS if s.name == "drive")

    _line1, line2 = drive_screen.render({"halted_on_contact": False})

    assert line2 == "running"
```

Append to `pathfinder-autonomous/pi-mission/tests/test_status_display_integration.py` (it already imports `httpx`, `FakeEsp32Link`, `GpsFix`, `ImuReading`, `MissionRuntime`, `SimulatedSensorHub`, `DEFAULT_SCREENS`, `StatusDisplay`, and defines `INITIAL_IMU`/`FIELD_RING`/`_handler`/`_FakeLcdWriter` — reuse them, do not redefine):

```python
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

    runtime.esp32_link.status = _boom
    runtime._last_telemetry_sample_monotonic = 0.0  # force a sample this tick
    runtime.tick()  # must not raise

    lcd = _FakeLcdWriter()
    display = StatusDisplay(lcd=lcd)
    for _ in range(3):  # cycle position -> mission -> obstacles -> drive
        display.next_screen()
    display.refresh(runtime.last_telemetry_readings)

    assert lcd.writes[0][1] == "LINK?"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run (from `pathfinder-autonomous/pi-mission/`):
`pytest tests/test_status_display.py tests/test_status_display_integration.py -k "link_unknown or explicit_false or status_read_fails" -v`

Expected: FAIL — the two unit tests fail with `AssertionError: assert 'running' == 'LINK?'` (current code returns `"running"` for an empty/no-key state); the integration test fails the same way (`AssertionError: assert 'running' == 'LINK?'`).

- [ ] **Step 3: Write the implementation**

In `papaya_mission/status_display.py`, find this exact existing function:

```python
def _render_drive(state: dict[str, Any]) -> tuple[str, str]:
    throttle = state.get("throttle_position", 0.0)
    halted = state.get("halted_on_contact", False)
    return (f"Throttle: {throttle:.2f}", "HALTED" if halted else "running")
```

Replace it with:

```python
def _render_drive(state: dict[str, Any]) -> tuple[str, str]:
    throttle = state.get("throttle_position", 0.0)
    if "halted_on_contact" not in state:
        # Absent, not False: either the ESP32 status read failed this
        # sample (see MissionRuntime._sample_telemetry_if_due) or no
        # sample has completed yet. Neither is "confirmed not halted".
        status_text = "LINK?"
    else:
        status_text = "HALTED" if state["halted_on_contact"] else "running"
    return (f"Throttle: {throttle:.2f}", status_text)
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_status_display.py tests/test_status_display_integration.py -v`
Expected: PASS (all tests in both files, including the 3 new ones)

- [ ] **Step 5: Run the full test suite and verify everything passes**

Run: `pytest -v` (from `pathfinder-autonomous/pi-mission/`)
Expected: PASS — all prior tests plus this plan's 3 new tests (count the real total from your own run).

- [ ] **Step 6: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/status_display.py pathfinder-autonomous/pi-mission/tests/test_status_display.py pathfinder-autonomous/pi-mission/tests/test_status_display_integration.py
git commit -m "fix(pi-mission): distinguish unknown drive-halted state from confirmed not-halted"
```
