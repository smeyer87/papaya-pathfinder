# PositionFusion Heading-Staleness Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `PositionFusion`'s fused heading so it updates every tick from the real IMU reading, instead of only on ticks where no GPS fix arrived — on a GPS-healthy rover (the common case) it currently never advances past its seed value, silently misplacing every obstacle `obstacle_detection.py` logs.

**Architecture:** Add a narrow `PositionFusion.on_imu_heading(heading_deg)` method that updates only `_heading_deg`, with no dt guard — so it can't be silently skipped the way `on_imu_reading`'s dead-reckoning path can. `MissionRuntime._read_position` calls it unconditionally every tick, before branching on GPS-fix availability. Also fixes a related gap: the very first `PositionFusion` seeds `initial_heading_deg=0.0` by default even though a real IMU reading was already read that tick.

**Tech Stack:** Python 3.12, pytest. No new dependencies.

## Global Constraints

- `PositionFusion.on_gps_fix` and `on_imu_reading`'s existing dead-reckoning behavior (position/velocity/error-radius) are unchanged — both are already correct and tested. Only heading-update coverage is being fixed.
- The new `on_imu_heading` method has no `dt`/timestamp guard — it is an unconditional assignment, unlike `on_imu_reading`.
- No change to `obstacle_detection.py` — it already correctly consumes `rover_position.heading_deg`; the bug was entirely in that value being stale.
- Design spec: `docs/superpowers/specs/2026-10-02-position-fusion-heading-staleness-design.md`.

---

## File Structure

```
pathfinder-autonomous/pi-mission/
  papaya_mission/
    position_fusion.py   # MODIFY -- add on_imu_heading method
    runtime.py            # MODIFY -- _read_position, two call sites
  tests/
    test_position_fusion.py        # MODIFY -- 2 new unit tests
    test_runtime_tick_sensing.py   # MODIFY -- 2 new integration tests
```

---

### Task 1: Add `on_imu_heading` and wire it into every tick

**Files:**
- Modify: `pathfinder-autonomous/pi-mission/papaya_mission/position_fusion.py`
- Modify: `pathfinder-autonomous/pi-mission/papaya_mission/runtime.py`
- Modify: `pathfinder-autonomous/pi-mission/tests/test_position_fusion.py`
- Modify: `pathfinder-autonomous/pi-mission/tests/test_runtime_tick_sensing.py`

**Interfaces:**
- Consumes: `papaya_mission.sensor_hub.SimulatedSensorHub.script_imu_reading(reading: ImuReading) -> None` (unchanged, existing — sets the IMU's "current" reading, not consume-once).
- Produces: `PositionFusion.on_imu_heading(heading_deg: float) -> None` — nothing consumed by a later task; this plan has one task.

- [ ] **Step 1: Write the failing unit tests**

Append to `pathfinder-autonomous/pi-mission/tests/test_position_fusion.py` (it already imports `GpsFix`, `ImuReading`, `PositionEstimate`, `PositionFusion` — reuse them):

```python
def test_on_imu_heading_updates_heading_only():
    fix = GpsFix(lat=38.0, lon=-85.0, accuracy_m=2.0, timestamp=0.0)
    fusion = PositionFusion(fix, initial_heading_deg=45.0)
    before = fusion.current_estimate

    fusion.on_imu_heading(270.0)

    after = fusion.current_estimate
    assert after.heading_deg == 270.0
    assert after.lat == before.lat
    assert after.lon == before.lon
    assert after.error_radius_m == before.error_radius_m
    assert after.timestamp == before.timestamp


def test_on_imu_heading_works_independent_of_gps_fix_order():
    fix = GpsFix(lat=38.0, lon=-85.0, accuracy_m=2.0, timestamp=0.0)
    fusion = PositionFusion(fix, initial_heading_deg=45.0)

    corrected = fusion.on_gps_fix(
        GpsFix(lat=38.001, lon=-85.001, accuracy_m=1.5, timestamp=1.0)
    )
    assert corrected.heading_deg == 45.0  # unchanged by the GPS fix itself

    fusion.on_imu_heading(180.0)

    after = fusion.current_estimate
    assert after.heading_deg == 180.0
    assert after.lat == 38.001  # GPS-fixed position untouched by the heading update
    assert after.lon == -85.001
```

- [ ] **Step 2: Run the unit tests and verify they fail**

Run (from `pathfinder-autonomous/pi-mission/`): `pytest tests/test_position_fusion.py -k on_imu_heading -v`
Expected: FAIL — `AttributeError: 'PositionFusion' object has no attribute 'on_imu_heading'`

- [ ] **Step 3: Write the `on_imu_heading` implementation**

In `papaya_mission/position_fusion.py`, find this exact existing method (`on_gps_fix`'s closing lines, immediately followed by `on_imu_reading`'s definition):

```python
        self._last_timestamp = fix.timestamp
        return self.current_estimate

    def on_imu_reading(self, reading: ImuReading) -> PositionEstimate:
```

Insert a new method between them:

```python
        self._last_timestamp = fix.timestamp
        return self.current_estimate

    def on_imu_heading(self, heading_deg: float) -> None:
        """Updates heading only, independent of position dead-reckoning.
        Unlike on_imu_reading, this has no dt guard -- it is called
        unconditionally every tick regardless of whether a fresh GPS fix
        is also available that tick, since heading comes from the IMU
        compass and has nothing to do with GPS availability (unlike
        position/error-radius/velocity, which follow the GPS-fix-resets /
        IMU-dead-reckons-between-fixes pattern in on_gps_fix/
        on_imu_reading).
        """
        self._heading_deg = heading_deg

    def on_imu_reading(self, reading: ImuReading) -> PositionEstimate:
```

- [ ] **Step 4: Run the unit tests and verify they pass**

Run: `pytest tests/test_position_fusion.py -v`
Expected: PASS (all tests in the file, including the 2 new ones)

- [ ] **Step 5: Write the failing integration tests**

Append to `pathfinder-autonomous/pi-mission/tests/test_runtime_tick_sensing.py` (it already imports `GpsFix`, `ImuReading`, `SimulatedSensorHub`, `MissionRuntime`, and defines `_make_started_runtime`/`INITIAL_IMU` — reuse them, do not redefine):

```python
def test_heading_updates_every_tick_even_when_gps_is_healthy(tmp_path):
    """Regression test for the bug: PositionFusion._heading_deg only
    updated when no GPS fix arrived that tick, so on a GPS-healthy rover
    (a fix arriving almost every tick) it never advanced past its seed
    value. Scripts a GPS fix on every tick (the previously-broken case)
    and confirms heading still tracks the scripted IMU reading.
    """
    hub = SimulatedSensorHub(INITIAL_IMU)
    runtime = _make_started_runtime(tmp_path, sensor_hub=hub)
    hub.script_gps_fix(GpsFix(lat=38.05, lon=-85.0, accuracy_m=2.0, timestamp=0.0))
    runtime.tick()  # seeds position_fusion
    assert runtime.position_fusion.current_estimate.heading_deg == 0.0  # INITIAL_IMU's heading

    hub.script_imu_reading(
        ImuReading(heading_deg=123.0, forward_acceleration_mps2=0.0, timestamp=1.0)
    )
    hub.script_gps_fix(GpsFix(lat=38.05, lon=-85.0, accuracy_m=2.0, timestamp=1.0))  # fix again this tick
    runtime.tick()

    assert runtime.position_fusion.current_estimate.heading_deg == 123.0


def test_seed_tick_captures_the_real_imu_heading_not_zero(tmp_path):
    """Regression test for the related seed-time gap: the very first
    PositionFusion defaulted initial_heading_deg to 0.0 even though a
    real IMU reading was already read that same tick.
    """
    hub = SimulatedSensorHub(
        ImuReading(heading_deg=200.0, forward_acceleration_mps2=0.0, timestamp=0.0)
    )
    runtime = _make_started_runtime(tmp_path, sensor_hub=hub)
    hub.script_gps_fix(GpsFix(lat=38.05, lon=-85.0, accuracy_m=2.0, timestamp=0.0))

    runtime.tick()  # this tick seeds position_fusion

    assert runtime.position_fusion.current_estimate.heading_deg == 200.0
```

- [ ] **Step 6: Run the integration tests and verify they fail**

Run: `pytest tests/test_runtime_tick_sensing.py -k "heading_updates_every_tick or seed_tick_captures" -v`
Expected: FAIL — `test_heading_updates_every_tick_even_when_gps_is_healthy` fails with `assert 0.0 == 123.0` (heading stuck at its seed value); `test_seed_tick_captures_the_real_imu_heading_not_zero` fails with `assert 0.0 == 200.0` (seed defaulted to 0.0 instead of the real IMU reading)

- [ ] **Step 7: Write the `runtime.py` implementation**

In `papaya_mission/runtime.py`'s `_read_position`, find this exact existing block:

```python
        if self.position_fusion is None:
            seed_fix = gps_fix or GpsFix(lat=0.0, lon=0.0, accuracy_m=999.0, timestamp=imu_reading.timestamp)
            self.position_fusion = PositionFusion(seed_fix)
            # The clock starts here whether or not a REAL fix arrived. When it
            # did not, we are seeding from the dummy (0,0)/999m fix, and
            # leaving _last_gps_fix_monotonic as None made _check_gps_loss
            # return immediately forever: a cold boot under tree cover with
            # zero fixes ever acquired never evaluated GPS-loss safety at all,
            # however long dead reckoning ran. "Never had a fix" is at least
            # as unsafe as "just lost one", so it starts the same
            # grace-period clock rather than disabling the check.
            self._last_gps_fix_monotonic = now_monotonic
            return

        if gps_fix is not None:
            self.position_fusion.on_gps_fix(gps_fix)
            self._last_gps_fix_monotonic = now_monotonic
        else:
            self.position_fusion.on_imu_reading(imu_reading)
```

Replace it with:

```python
        if self.position_fusion is None:
            seed_fix = gps_fix or GpsFix(lat=0.0, lon=0.0, accuracy_m=999.0, timestamp=imu_reading.timestamp)
            self.position_fusion = PositionFusion(seed_fix, initial_heading_deg=imu_reading.heading_deg)
            # The clock starts here whether or not a REAL fix arrived. When it
            # did not, we are seeding from the dummy (0,0)/999m fix, and
            # leaving _last_gps_fix_monotonic as None made _check_gps_loss
            # return immediately forever: a cold boot under tree cover with
            # zero fixes ever acquired never evaluated GPS-loss safety at all,
            # however long dead reckoning ran. "Never had a fix" is at least
            # as unsafe as "just lost one", so it starts the same
            # grace-period clock rather than disabling the check.
            self._last_gps_fix_monotonic = now_monotonic
            return

        # Heading comes from the IMU compass every tick, regardless of GPS
        # fix availability -- unlike position/error-radius/velocity, which
        # only dead-reckon in on_imu_reading() below when no fix arrived.
        # Calling this unconditionally is what fixes the bug where heading
        # never advanced past its seed value on a GPS-healthy rover (a fix
        # arriving most ticks meant on_imu_reading, the only method that
        # used to update heading, almost never ran).
        self.position_fusion.on_imu_heading(imu_reading.heading_deg)

        if gps_fix is not None:
            self.position_fusion.on_gps_fix(gps_fix)
            self._last_gps_fix_monotonic = now_monotonic
        else:
            self.position_fusion.on_imu_reading(imu_reading)
```

- [ ] **Step 8: Run the integration tests and verify they pass**

Run: `pytest tests/test_runtime_tick_sensing.py -v`
Expected: PASS (all tests in the file, including the 2 new ones)

- [ ] **Step 9: Run the full test suite and verify everything passes**

Run: `pytest -v` (from `pathfinder-autonomous/pi-mission/`)
Expected: PASS — all prior tests plus this plan's 4 new tests (count the real total from your own run). Note: there is a KNOWN, pre-existing, unrelated flaky test group (`tests/test_digital_twin_scenarios.py`, `tests/test_hardware_drivers_integration.py` — timing-sensitive, documented in `docs/phase2/inputs/00-inbox.md`) that can occasionally show a few failures under full-suite wall-clock load. If you see ONLY those fail, re-run them in isolation to confirm, and don't treat it as caused by this change.

- [ ] **Step 10: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/position_fusion.py pathfinder-autonomous/pi-mission/papaya_mission/runtime.py pathfinder-autonomous/pi-mission/tests/test_position_fusion.py pathfinder-autonomous/pi-mission/tests/test_runtime_tick_sensing.py
git commit -m "fix(pi-mission): update fused heading every tick, not just when GPS is unavailable"
```
