# PositionFusion Heading-Staleness Bug — Design

**Status:** Approved, pending plan
**Related:** `pathfinder-autonomous/pi-mission/papaya_mission/position_fusion.py`, `papaya_mission/runtime.py`

## Problem

`PositionFusion._heading_deg` only updates inside `on_imu_reading()`, which is the method that also does full dead-reckoning (position/velocity/error-radius). `MissionRuntime._read_position` (`runtime.py:315-361`) calls `on_imu_reading` **only** in the `else` branch — when no GPS fix arrived that tick:

```python
if gps_fix is not None:
    self.position_fusion.on_gps_fix(gps_fix)
    self._last_gps_fix_monotonic = now_monotonic
else:
    self.position_fusion.on_imu_reading(imu_reading)
```

On a GPS-healthy rover (the common case — a fix arrives almost every tick), `on_imu_reading` essentially never runs, so `_heading_deg` never advances past whatever it was seeded at. `obstacle_from_ultrasonic_camera_detection` (`obstacle_detection.py`) projects every detection's absolute bearing using `rover_position.heading_deg` — so every logged obstacle gets placed using a stale/zero heading, silently misplacing it, whenever GPS is working normally (i.e. almost always).

A second, related bug compounds this: the very first `PositionFusion` ever constructed, at seed time (`runtime.py:343-345`), also doesn't get a real heading —

```python
self.position_fusion = PositionFusion(seed_fix)
```

— defaults `initial_heading_deg` to `0.0`, even though a real `imu_reading` was already successfully read that same tick (the method returns early with an IMU read failure before reaching this line, so `imu_reading` is guaranteed valid here).

This bug was found during the digital-twin simulator's final review (2026-09-26), logged to memory, explicitly scoped out of that plan as pre-existing and unrelated — never fixed until now.

## `PositionFusion` itself is correct and already tested — the bug is entirely in the caller

`position_fusion.py`'s `on_gps_fix` deliberately never touches heading (position/velocity/error-radius only) — there's an existing, passing test for exactly this: `test_gps_fix_does_not_change_heading` asserts `corrected.heading_deg == 90.0  # unchanged by the GPS fix`. This is correct design: a GPS fix carries no heading information of its own, so `on_gps_fix` has nothing to update heading with. The bug is that nothing else steps in to update heading on a tick where `on_gps_fix` runs instead of `on_imu_reading`.

## Fix

Add a narrow, dedicated method to `PositionFusion` that updates **only** heading — no dt guard, no dead-reckoning math, so it can never be silently skipped the way `on_imu_reading`'s `if dt <= 0: return` guard could skip it:

```python
def on_imu_heading(self, heading_deg: float) -> None:
    self._heading_deg = heading_deg
```

Call it unconditionally, every tick, in `_read_position` — before the `gps_fix is not None` branch, so it runs regardless of which branch follows:

```python
self.position_fusion.on_imu_heading(imu_reading.heading_deg)
if gps_fix is not None:
    self.position_fusion.on_gps_fix(gps_fix)
    self._last_gps_fix_monotonic = now_monotonic
else:
    self.position_fusion.on_imu_reading(imu_reading)
```

In the no-fix branch, `on_imu_reading` will set the same heading value again — harmless redundancy, not worth adding a conditional to avoid, since correctness (heading always reflects the latest real reading) matters more than skipping one redundant assignment.

Also fix the seed-time gap: pass the real heading when constructing the first `PositionFusion`:

```python
self.position_fusion = PositionFusion(seed_fix, initial_heading_deg=imu_reading.heading_deg)
```

## Why not fold heading into `on_gps_fix` instead

Considered and rejected: calling `on_imu_reading` unconditionally every tick (even when a GPS fix also arrives) instead of adding a new method. Rejected because `on_imu_reading`'s `dt <= 0` guard (comparing `ImuReading.timestamp` against `_last_timestamp`) could still silently skip the heading update under certain tick-timing edge cases — real hardware's IMU and GPS readings may come from clocks that aren't perfectly synchronized, so this doesn't fully close the bug, just narrows it. A dedicated, guard-free method closes it completely and leaves the already-tested `on_gps_fix`/`on_imu_reading` dead-reckoning contracts untouched.

## Testing

- `tests/test_position_fusion.py`: a new unit test constructing `PositionFusion`, calling `on_imu_heading(90.0)` directly, and asserting `current_estimate.heading_deg == 90.0` with no position/velocity/error-radius side effects (compare against the state immediately after construction for every other field).
- A new test confirming `on_imu_heading` works independent of `on_gps_fix`/`on_imu_reading` call order — e.g. call `on_gps_fix` first (which doesn't touch heading, per the existing test), then `on_imu_heading`, and confirm heading updates while position stays at the GPS fix's value.
- `tests/test_runtime_tick_sensing.py`: a new integration-style test using the existing `_make_started_runtime`/`SimulatedSensorHub` fixtures — script an `ImuReading` with a non-zero heading alongside a GPS fix that arrives every tick (the common, previously-broken case), tick `MissionRuntime`, and assert `runtime.position_fusion.current_estimate.heading_deg` reflects the scripted IMU heading, not `0.0` or the seed value. This is the actual regression guard for the bug as experienced in production.
- A new test for the seed-time fix: assert that `position_fusion.current_estimate.heading_deg` on the very first tick (where `PositionFusion` is constructed) already reflects the scripted IMU heading, not the `0.0` default.

## Out of scope

- No change to `obstacle_detection.py` — it already correctly consumes `rover_position.heading_deg`; the bug was entirely in that value being stale, not in how it's used.
- No change to `on_gps_fix`'s or `on_imu_reading`'s existing dead-reckoning behavior.
