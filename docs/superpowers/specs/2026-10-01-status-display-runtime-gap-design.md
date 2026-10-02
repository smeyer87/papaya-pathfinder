# StatusDisplay / Runtime State Gap — Design

**Status:** Approved, pending plan
**Related:** `docs/superpowers/plans/2026-09-30-breadboard-hardware-drivers.md` (where the gap was found), `pathfinder-autonomous/pi-mission/papaya_mission/status_display.py`, `pathfinder-autonomous/pi-mission/papaya_mission/runtime.py`

## Problem

`status_display.py`'s four default screens (`_render_position`, `_render_mission`, `_render_obstacles`, `_render_drive`) read a `dict[str, Any]` state snapshot that `MissionRuntime` does not currently produce anywhere:

- The closest candidate, `readings`, is a local variable built fresh inside `_sample_telemetry_if_due` every `TELEMETRY_SAMPLE_INTERVAL_S` and handed straight to `build_telemetry_record` — never stored on `self`, so nothing outside that one method can read it.
- `build_telemetry_record`'s output isn't a substitute either: it replaces every key outside the caller's `expected_metrics` with the string `"missing"` (`telemetry_record.py:28`). `_render_position`'s `position is None` guard doesn't catch that sentinel, so unpacking `lon, lat = "missing"` raises.
- `obstacle_count`, `last_obstacle_type`, and `halted_on_contact` are not tracked as runtime state at all today. Obstacles are persisted to `local_store` one row at a time with no running count kept; `halted_on_contact` is read from `self.esp32_link.status()` only inside `_handle_resume_sweep`, a command handler that isn't called every tick.

Net effect: there is currently no way to wire a live `StatusDisplay` to a real `MissionRuntime` without it crashing or showing permanently-empty obstacle/drive screens.

## Decisions made during brainstorming

- **Scope: local/live only, not synced.** The three new fields get added to a live snapshot the LCD reads, but are deliberately kept out of `MP1_EXPECTED_METRICS` (`runtime_config.py`) and the backend sync path. Adding them to the ground-control telemetry package is a good long-term idea but a separate, bigger-picture change — logged as a follow-up, not built here.
- **Obstacle counter scope: count all detections.** `_save_obstacle()` currently returns early (without persisting) when no sweep session is active. The new counter increments regardless — it answers "what has the rover reacted to," not "what got a durable row."
- **Obstacle counter lifetime: resets per sweep session.** Zeroed in `handle_start_sweep()`, so the LCD shows "this mission," not a lifetime total that keeps climbing across a bench day of many short test sweeps.

## Architecture

All changes are additive to `runtime.py` (and its tests). **`status_display.py` itself needs no changes** — its renderers were already written against exactly this state shape; the gap was entirely on the producing side.

### New `MissionRuntime` state

```python
self.last_telemetry_readings: dict[str, Any] = {}
self._obstacle_count: int = 0
self._last_obstacle_type: str = "-"
```

Declared in `__init__` alongside the other per-task state fields, consistent with the file's existing "declared here so every task's tests can construct one consistent `__init__`" convention.

### `_sample_telemetry_if_due`: expose the pre-sentinel snapshot, add the missing fields

After `readings` is fully built (same point where it's currently handed to `build_telemetry_record`), add the three new keys and store the snapshot:

```python
readings["obstacle_count"] = self._obstacle_count
readings["last_obstacle_type"] = self._last_obstacle_type

try:
    halted_on_contact = self.esp32_link.status().halted_on_contact
except Exception:
    logger.warning("ESP32 status read failed -- leaving halted_on_contact out of this sample", exc_info=True)
    halted_on_contact = None
if halted_on_contact is not None:
    readings["halted_on_contact"] = halted_on_contact

self.last_telemetry_readings = readings
```

This mirrors the existing `read_drive_status()` try/except immediately above it (same file, same method) — a transient ESP32-link failure degrades this one field for this one sample rather than raising. `last_telemetry_readings` is assigned the *same* `readings` dict that (minus these three keys, since they're not in `expected_metrics`) goes on to `build_telemetry_record` — one dict, two uses, no duplication.

### `_save_obstacle`: count every detection

```python
def _save_obstacle(self, obstacle, *, obstacle_id: str | None = None) -> None:
    self._obstacle_count += 1
    self._last_obstacle_type = obstacle.type
    if self.sweep_session is None:
        return
    ...  # unchanged
```

Placed before the existing early-return so it fires whether or not the obstacle gets persisted, per the "count all detections" decision.

### `handle_start_sweep`: reset the counter

```python
def handle_start_sweep(self, payload: dict[str, Any]) -> None:
    self._obstacle_count = 0
    self._last_obstacle_type = "-"
    ...  # existing body
```

`"-"` matches `_render_obstacles`'s own existing default (`state.get("last_obstacle_type", "-")`), so a fresh session and a session with no obstacles yet render identically.

## Testing

- **Unit tests in `test_runtime_*`** (extending whichever existing test module already covers `_sample_telemetry_if_due`/`_save_obstacle`/`handle_start_sweep`):
  - `last_telemetry_readings` is populated after a tick and contains `obstacle_count`, `last_obstacle_type`, and (when the fake `Esp32Link` reports a status) `halted_on_contact`.
  - `_obstacle_count` increments on a bump contact with no active sweep session (count-all-detections behavior), and the obstacle is *not* persisted to `local_store` in that case (existing behavior, now explicitly asserted alongside the count).
  - `_obstacle_count`/`_last_obstacle_type` reset to `0`/`"-"` when `handle_start_sweep` starts a new session, even if a prior session left them non-zero.
  - A failing `esp32_link.status()` degrades only `halted_on_contact` for that sample (the rest of `readings` is unaffected), matching the existing `read_drive_status` failure-handling test's shape.
- **New integration test**: construct a real `MissionRuntime`, drive it through `startup()` → `handle_start_sweep()` → a few `tick()` calls with a fake sensor hub that reports a bump/obstacle, then construct a real `StatusDisplay` and call `.refresh(runtime.last_telemetry_readings)` for each of the four `DEFAULT_SCREENS`, asserting each renders without raising and that the obstacle/drive screens show the expected non-default values (not just "doesn't crash" — the earlier integration test from the hardware-drivers plan proved connectivity without ever exercising `status_display.py`; this one specifically closes that gap).

## Out of scope / follow-ups

- Adding `obstacle_count`/`last_obstacle_type`/`halted_on_contact` to `MP1_EXPECTED_METRICS` and the backend sync path — deferred per the user's explicit call to keep this bench-focused for now.
- Any change to `status_display.py` itself — not needed; the gap was entirely in what `runtime.py` exposed.
- Real hardware wiring (`StatusDisplay` + a real LCD backend) — already covered by the breadboard hardware-drivers plan's bench-time scope, unaffected by this change.
