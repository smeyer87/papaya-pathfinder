# Drive-Screen Halted/Running Ambiguity — Design

**Status:** Approved, pending plan
**Related:** `docs/phase2/inputs/00-inbox.md` (follow-up logged 2026-10-01), `pathfinder-autonomous/pi-mission/papaya_mission/status_display.py`

## Problem

`_render_drive`'s current implementation:

```python
def _render_drive(state: dict[str, Any]) -> tuple[str, str]:
    throttle = state.get("throttle_position", 0.0)
    halted = state.get("halted_on_contact", False)
    return (f"Throttle: {throttle:.2f}", "HALTED" if halted else "running")
```

`state.get("halted_on_contact", False)` cannot distinguish "confirmed not halted" from "the key is absent." The key is genuinely absent in two real situations:

- `MissionRuntime._sample_telemetry_if_due` omits `halted_on_contact` from `last_telemetry_readings` whenever `esp32_link.status()` raises — a deliberate choice (don't assert a not-halted state that wasn't actually confirmed), added in the runtime-state-gap plan.
- Before the very first telemetry sample ever completes, `last_telemetry_readings == {}`.

In both cases, the LCD currently shows "running" — exactly the moment a bench operator would be looking at the screen to find out whether the rover is actually stuck.

## Fix

Check key presence instead of relying on a default value, and give the "we don't know" case its own distinct label:

```python
def _render_drive(state: dict[str, Any]) -> tuple[str, str]:
    throttle = state.get("throttle_position", 0.0)
    if "halted_on_contact" not in state:
        status_text = "LINK?"
    else:
        status_text = "HALTED" if state["halted_on_contact"] else "running"
    return (f"Throttle: {throttle:.2f}", status_text)
```

`"LINK?"` fits well within the 16-character line width alongside `"Throttle: X.XX"` (15 chars). Localized to `_render_drive` only — no other screen has this ambiguity: `obstacle_count`/`last_obstacle_type`/`nav_mode`/`mission_alert` are all either always present once any sample has run, or have a default that's correct even pre-sample.

## Testing

- `pathfinder-autonomous/pi-mission/tests/test_status_display.py`: the existing `test_default_screens_render_without_raising_on_an_empty_state` only asserts `isinstance(line1, str)`/`isinstance(line2, str)` — it does not assert specific content, so it needs no change and will continue to pass (now rendering `"LINK?"` instead of `"running"` for the drive screen on an empty state, which is more correct, not a regression). Add one new, more targeted unit test asserting the unknown-state path explicitly: `_render_drive({})` (or any dict missing `"halted_on_contact"`) returns `"LINK?"` as its second line, and `_render_drive({"halted_on_contact": False})` still returns `"running"` (confirms the fix didn't flip the meaning of an explicit `False`).
- `pathfinder-autonomous/pi-mission/tests/test_status_display_integration.py`: add one new integration test alongside the existing `test_status_display_renders_real_runtime_state_without_raising`, following its exact fixture pattern (real `MissionRuntime`, real `StatusDisplay`, `_FakeLcdWriter`). Monkeypatch `runtime.esp32_link.status` to raise (matching the pattern already used in `test_runtime_tick_sensing.py`'s `_boom` helper), force a telemetry sample, tick, then assert the drive screen's rendered second line is `"LINK?"` — proving the fix holds end-to-end through a real runtime tick, not just at the renderer-function level.

## Out of scope

- No changes to `runtime.py` — `last_telemetry_readings` already omits the key correctly on a failed read; this fix is entirely on the consuming side.
- No changes to any other screen's renderer.
