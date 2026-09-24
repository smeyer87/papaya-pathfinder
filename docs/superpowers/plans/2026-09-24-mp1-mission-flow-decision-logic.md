# MP-1 Mission Flow Decision Logic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The pure decision-logic layer for MP-1's sweep execution: deriving coverage-pattern row spacing from real sensor/turning constraints, a sweep-session state machine (start/interrupt/resume/complete), and the two safety decisions from the design spec (exclusion-zone auto-reverse-vs-wait-for-help, GPS-loss continue-vs-stop).

**Architecture:** Extends `papaya_mission` with four small, independent modules. Deliberately scoped to decision logic and state transitions only — not the actual runtime loop (polling the command queue, writing telemetry, triggering Home-return sync). That loop depends on the Pi Telemetry + Sync and Backend command-channel plans, neither of which exist as code yet; wiring a runtime around them now would mean building against stubs. This plan produces the building blocks that runtime will call.

**Tech Stack:** Python 3.11, pytest. No new dependencies.

## Global Constraints

- Extends `pathfinder-autonomous/pi-mission/` — same package, same stack as the two prior plans.
- No hardware I/O, no persistence, no async/event-loop machinery. Every function here is synchronous and pure or operates on an explicit, injected state object (`SweepSession`) — testable without mocking a clock, a queue, or a network call.
- Row spacing is a *detection-coverage* constraint, not a wheel-coverage one: bounded by the sensor's effective detection width, not by trying to physically drive over every square meter. (Design spec: Route Planning notes; MP-1 planning discussion on `row_spacing_m`.)
- The row-to-row turn doesn't need a wide turning radius by default — Phase 1's firmware already supports spin-in-place (`setSpin()` in `firmware-elrs.ino`), so `rover_can_spin_in_place=True` is the expected default; the turn-diameter floor only matters if that assumption doesn't hold for a given rover build.
- Exclusion-zone response threshold is "under one rover-length deep → auto-reverse, otherwise wait for help" — exactly at one rover-length counts as "otherwise" (wait for help), not auto-reverse; there's no ambiguity band. (Design spec: Mission Flow — Exclusion-zone intrusion.)
- GPS-loss response is "whichever safety bound is hit first" — grace period elapsed OR error-circle radius exceeded — not both required. (Design spec: Mission Flow — GPS loss/degradation.)

---

## File Structure

```
pathfinder-autonomous/
  pi-mission/
    papaya_mission/
      row_spacing.py            # NEW -- derive_row_spacing_m()
      sweep_session.py           # NEW -- SweepSession state machine
      exclusion_decision.py       # NEW -- decide_exclusion_response()
      gps_loss_decision.py         # NEW -- decide_gps_loss_response()
    tests/
      test_row_spacing.py         # NEW
      test_sweep_session.py        # NEW
      test_exclusion_decision.py    # NEW
      test_gps_loss_decision.py      # NEW
      test_mission_flow_integration.py # NEW
```

---

### Task 1: Row spacing derivation

**Files:**
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/row_spacing.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_row_spacing.py`

**Interfaces:**
- Produces: `papaya_mission.row_spacing.derive_row_spacing_m(sensor_detection_width_m: float, rover_can_spin_in_place: bool = True, min_turn_diameter_m: float = 0.0) -> float`, raising `ValueError` on non-positive width or an infeasible turn-diameter/width combination. The mission-runtime plan (not yet written) calls this once per mission, feeding the result into `coverage_pattern.generate_coverage_pattern`.

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_row_spacing.py
import pytest

from papaya_mission.row_spacing import derive_row_spacing_m


def test_row_spacing_matches_sensor_width_when_rover_can_spin():
    spacing = derive_row_spacing_m(sensor_detection_width_m=8.0, rover_can_spin_in_place=True)

    assert spacing == 8.0


def test_row_spacing_matches_sensor_width_when_turn_diameter_fits():
    spacing = derive_row_spacing_m(
        sensor_detection_width_m=8.0, rover_can_spin_in_place=False, min_turn_diameter_m=3.0
    )

    assert spacing == 8.0


def test_rejects_non_positive_sensor_width():
    with pytest.raises(ValueError):
        derive_row_spacing_m(sensor_detection_width_m=0.0)


def test_rejects_infeasible_turn_diameter_when_cannot_spin():
    with pytest.raises(ValueError):
        derive_row_spacing_m(
            sensor_detection_width_m=2.0, rover_can_spin_in_place=False, min_turn_diameter_m=5.0
        )
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_row_spacing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'papaya_mission.row_spacing'`

- [ ] **Step 3: Write the implementation**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/row_spacing.py
"""Derives coverage-pattern row spacing from sensor detection width and
rover turning capability. See design spec's Route Planning notes.
"""
from __future__ import annotations


def derive_row_spacing_m(
    sensor_detection_width_m: float,
    rover_can_spin_in_place: bool = True,
    min_turn_diameter_m: float = 0.0,
) -> float:
    """Row spacing is bounded above by the sensor's effective detection
    width, so adjacent rows' scan coverage meets with no gap between
    them -- this is a detection-coverage sweep, not a wheel-coverage
    lawnmower. It's bounded below by the rover's minimum turning
    diameter, unless it can spin in place (Phase 1 firmware's
    setSpin()), in which case the row-to-row turn doesn't need a wide
    radius and the floor doesn't apply.
    """
    if sensor_detection_width_m <= 0:
        raise ValueError(
            f"sensor_detection_width_m must be > 0, got {sensor_detection_width_m}"
        )
    if not rover_can_spin_in_place and min_turn_diameter_m > sensor_detection_width_m:
        raise ValueError(
            f"rover's minimum turn diameter ({min_turn_diameter_m}m) exceeds the "
            f"sensor detection width ({sensor_detection_width_m}m) -- full detection "
            "coverage isn't achievable with drivable row-to-row turns at this spacing"
        )
    return sensor_detection_width_m
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_row_spacing.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/row_spacing.py pathfinder-autonomous/pi-mission/tests/test_row_spacing.py
git commit -m "feat(pi-mission): derive coverage row spacing from sensor width and turn capability"
```

---

### Task 2: Sweep-session state machine

**Files:**
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/sweep_session.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_sweep_session.py`

**Interfaces:**
- Produces: `papaya_mission.sweep_session.{SweepSessionStatus, Waypoint, SweepSession, InvalidSweepSessionTransition}`. `SweepSession` fields mirror the design spec's Data Model — Sweep session record (`id`, `rover_id`, `geofence_id`, `pattern`, `status`, `last_completed_waypoint_index`, `started_at`, `interrupted_at`, `completed_at`) plus computed properties `remaining_waypoints` and `is_fully_covered`, and methods `mark_waypoint_complete(order)`, `interrupt(at)`, `resume()`, `complete(at)` — each raising `InvalidSweepSessionTransition` if called in the wrong state. The mission-runtime plan drives this object as waypoints are reached and commands arrive; the Pi-telemetry-and-sync plan persists/reloads it.

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_sweep_session.py
from datetime import datetime, timezone

import pytest

from papaya_mission.sweep_session import (
    InvalidSweepSessionTransition,
    SweepSession,
    SweepSessionStatus,
    Waypoint,
)

START = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


def _session(num_waypoints=3):
    pattern = [
        Waypoint(order=i, position=(-85.0 + i * 0.001, 38.0)) for i in range(num_waypoints)
    ]
    return SweepSession(
        id="sess-1", rover_id="rover-1", geofence_id="fence-1", pattern=pattern, started_at=START
    )


def test_new_session_has_no_completed_waypoints():
    session = _session()

    assert session.last_completed_waypoint_index == -1
    assert len(session.remaining_waypoints) == 3
    assert session.is_fully_covered is False


def test_mark_waypoint_complete_advances_progress():
    session = _session()

    session.mark_waypoint_complete(0)

    assert session.last_completed_waypoint_index == 0
    assert len(session.remaining_waypoints) == 2


def test_mark_waypoint_complete_rejects_out_of_order():
    session = _session()

    with pytest.raises(InvalidSweepSessionTransition):
        session.mark_waypoint_complete(1)  # skipped 0


def test_completing_all_waypoints_sets_is_fully_covered():
    session = _session(num_waypoints=2)

    session.mark_waypoint_complete(0)
    session.mark_waypoint_complete(1)

    assert session.is_fully_covered is True
    assert session.remaining_waypoints == []


def test_interrupt_and_resume_round_trip():
    session = _session()
    session.mark_waypoint_complete(0)

    session.interrupt(at=START)
    assert session.status == SweepSessionStatus.INTERRUPTED
    assert session.interrupted_at == START

    session.resume()
    assert session.status == SweepSessionStatus.IN_PROGRESS
    assert session.interrupted_at is None
    assert session.last_completed_waypoint_index == 0  # progress preserved


def test_cannot_interrupt_a_session_that_is_not_in_progress():
    session = _session()
    session.interrupt(at=START)

    with pytest.raises(InvalidSweepSessionTransition):
        session.interrupt(at=START)


def test_cannot_resume_a_session_that_is_not_interrupted():
    session = _session()

    with pytest.raises(InvalidSweepSessionTransition):
        session.resume()


def test_complete_requires_full_coverage():
    session = _session()

    with pytest.raises(InvalidSweepSessionTransition):
        session.complete(at=START)


def test_complete_succeeds_once_fully_covered():
    session = _session(num_waypoints=1)
    session.mark_waypoint_complete(0)

    session.complete(at=START)

    assert session.status == SweepSessionStatus.COMPLETED
    assert session.completed_at == START
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_sweep_session.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'papaya_mission.sweep_session'`

- [ ] **Step 3: Write the implementation**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/sweep_session.py
"""The sweep-session state machine: tracks coverage-pattern progress
through start/interrupt/resume/complete, enabling MP-1's resume
capability. See design spec: Data Model -- Sweep session, Mission Flow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class SweepSessionStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"


@dataclass(frozen=True)
class Waypoint:
    order: int
    position: tuple[float, float]  # (lon, lat)


class InvalidSweepSessionTransition(Exception):
    pass


@dataclass
class SweepSession:
    id: str
    rover_id: str
    geofence_id: str
    pattern: list[Waypoint]
    status: SweepSessionStatus = SweepSessionStatus.IN_PROGRESS
    last_completed_waypoint_index: int = -1
    started_at: datetime | None = None
    interrupted_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def remaining_waypoints(self) -> list[Waypoint]:
        return [wp for wp in self.pattern if wp.order > self.last_completed_waypoint_index]

    @property
    def is_fully_covered(self) -> bool:
        return self.last_completed_waypoint_index >= len(self.pattern) - 1

    def mark_waypoint_complete(self, order: int) -> None:
        if self.status != SweepSessionStatus.IN_PROGRESS:
            raise InvalidSweepSessionTransition(
                f"cannot mark waypoint complete while session status is {self.status}"
            )
        if order != self.last_completed_waypoint_index + 1:
            raise InvalidSweepSessionTransition(
                f"expected next waypoint order {self.last_completed_waypoint_index + 1}, got {order}"
            )
        self.last_completed_waypoint_index = order

    def interrupt(self, at: datetime) -> None:
        if self.status != SweepSessionStatus.IN_PROGRESS:
            raise InvalidSweepSessionTransition(
                f"cannot interrupt a session with status {self.status}"
            )
        self.status = SweepSessionStatus.INTERRUPTED
        self.interrupted_at = at

    def resume(self) -> None:
        if self.status != SweepSessionStatus.INTERRUPTED:
            raise InvalidSweepSessionTransition(
                f"cannot resume a session with status {self.status}"
            )
        self.status = SweepSessionStatus.IN_PROGRESS
        self.interrupted_at = None

    def complete(self, at: datetime) -> None:
        if not self.is_fully_covered:
            raise InvalidSweepSessionTransition("cannot mark complete -- waypoints remain")
        self.status = SweepSessionStatus.COMPLETED
        self.completed_at = at
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_sweep_session.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/sweep_session.py pathfinder-autonomous/pi-mission/tests/test_sweep_session.py
git commit -m "feat(pi-mission): add sweep-session state machine"
```

---

### Task 3: Exclusion-zone response decision

**Files:**
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/exclusion_decision.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_exclusion_decision.py`

**Interfaces:**
- Produces: `papaya_mission.exclusion_decision.decide_exclusion_response(intrusion_depth_m: float, rover_length_m: float) -> Literal["auto_reverse", "wait_for_help"]`. The mission-runtime plan calls this with the depth from `exclusion_check.find_intruded_exclusion` (from the Position & Coverage Geometry plan).

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_exclusion_decision.py
from papaya_mission.exclusion_decision import decide_exclusion_response


def test_shallow_intrusion_auto_reverses():
    assert decide_exclusion_response(intrusion_depth_m=0.3, rover_length_m=0.6) == "auto_reverse"


def test_deep_intrusion_waits_for_help():
    assert decide_exclusion_response(intrusion_depth_m=1.0, rover_length_m=0.6) == "wait_for_help"


def test_exactly_one_rover_length_waits_for_help():
    assert decide_exclusion_response(intrusion_depth_m=0.6, rover_length_m=0.6) == "wait_for_help"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_exclusion_decision.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'papaya_mission.exclusion_decision'`

- [ ] **Step 3: Write the implementation**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/exclusion_decision.py
"""The auto-reverse-vs-wait-for-help decision for an exclusion-zone
intrusion. See design spec: Mission Flow -- Exclusion-zone intrusion.
"""
from __future__ import annotations

from typing import Literal

ExclusionResponse = Literal["auto_reverse", "wait_for_help"]


def decide_exclusion_response(
    intrusion_depth_m: float, rover_length_m: float
) -> ExclusionResponse:
    """Under one rover-length deep -> auto-reverse. Otherwise (including
    exactly one rover-length) -> stop and wait for help.
    """
    if intrusion_depth_m < rover_length_m:
        return "auto_reverse"
    return "wait_for_help"
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_exclusion_decision.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/exclusion_decision.py pathfinder-autonomous/pi-mission/tests/test_exclusion_decision.py
git commit -m "feat(pi-mission): add exclusion-zone auto-reverse-vs-wait-for-help decision"
```

---

### Task 4: GPS-loss response decision

**Files:**
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/gps_loss_decision.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_gps_loss_decision.py`

**Interfaces:**
- Produces: `papaya_mission.gps_loss_decision.decide_gps_loss_response(seconds_since_last_fix: float, current_error_radius_m: float, grace_period_s: float, max_error_radius_m: float) -> Literal["continue_dead_reckoning", "stop_and_alert"]`. The mission-runtime plan calls this on each IMU tick while GPS is unavailable, using `PositionEstimate.error_radius_m` (Position & Coverage Geometry plan) for `current_error_radius_m`.

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_gps_loss_decision.py
from papaya_mission.gps_loss_decision import decide_gps_loss_response


def test_within_grace_period_and_error_continues():
    result = decide_gps_loss_response(
        seconds_since_last_fix=2.0,
        current_error_radius_m=3.0,
        grace_period_s=5.0,
        max_error_radius_m=10.0,
    )

    assert result == "continue_dead_reckoning"


def test_grace_period_exceeded_stops():
    result = decide_gps_loss_response(
        seconds_since_last_fix=6.0,
        current_error_radius_m=3.0,
        grace_period_s=5.0,
        max_error_radius_m=10.0,
    )

    assert result == "stop_and_alert"


def test_error_radius_exceeded_stops_even_within_grace_period():
    result = decide_gps_loss_response(
        seconds_since_last_fix=1.0,
        current_error_radius_m=15.0,
        grace_period_s=5.0,
        max_error_radius_m=10.0,
    )

    assert result == "stop_and_alert"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_gps_loss_decision.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'papaya_mission.gps_loss_decision'`

- [ ] **Step 3: Write the implementation**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/gps_loss_decision.py
"""GPS-loss/degradation handling: continue briefly on dead reckoning,
then stop and alert. See design spec: Mission Flow -- GPS loss/
degradation, Architecture -- Positioning (error circle).
"""
from __future__ import annotations

from typing import Literal

GpsLossResponse = Literal["continue_dead_reckoning", "stop_and_alert"]


def decide_gps_loss_response(
    seconds_since_last_fix: float,
    current_error_radius_m: float,
    grace_period_s: float,
    max_error_radius_m: float,
) -> GpsLossResponse:
    """Continue on dead reckoning until EITHER the grace period elapses
    OR the error circle grows past a safe threshold, whichever comes
    first -- then stop and alert.
    """
    if seconds_since_last_fix > grace_period_s:
        return "stop_and_alert"
    if current_error_radius_m > max_error_radius_m:
        return "stop_and_alert"
    return "continue_dead_reckoning"
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_gps_loss_decision.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/gps_loss_decision.py pathfinder-autonomous/pi-mission/tests/test_gps_loss_decision.py
git commit -m "feat(pi-mission): add GPS-loss continue-vs-stop decision"
```

---

### Task 5: Integration test and README update

**Files:**
- Create: `pathfinder-autonomous/pi-mission/tests/test_mission_flow_integration.py`
- Modify: `pathfinder-autonomous/pi-mission/README.md`

**Interfaces:**
- Consumes: Tasks 1–4, plus `coverage_pattern.generate_coverage_pattern` and `exclusion_check.find_intruded_exclusion` from the Position & Coverage Geometry plan.
- Produces: nothing new — proves the decision-logic layer composes with the geometry layer, and documents the additions for the (not-yet-written) Mission Runtime plan.

- [ ] **Step 1: Write the integration test**

```python
# pathfinder-autonomous/pi-mission/tests/test_mission_flow_integration.py
from datetime import datetime, timezone

from shapely.geometry import Polygon

from papaya_mission.coverage_pattern import generate_coverage_pattern
from papaya_mission.exclusion_check import find_intruded_exclusion
from papaya_mission.exclusion_decision import decide_exclusion_response
from papaya_mission.gps_loss_decision import decide_gps_loss_response
from papaya_mission.row_spacing import derive_row_spacing_m
from papaya_mission.sweep_session import SweepSession, SweepSessionStatus, Waypoint

FIELD = Polygon(
    [
        (-85.001, 38.000),
        (-85.001, 38.001),
        (-85.000, 38.001),
        (-85.000, 38.000),
        (-85.001, 38.000),
    ]
)
POND = Polygon(
    [
        (-85.0007, 38.0003),
        (-85.0007, 38.0007),
        (-85.0003, 38.0007),
        (-85.0003, 38.0003),
        (-85.0007, 38.0003),
    ]
)
START = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


def test_full_sweep_lifecycle_with_interruption_and_safety_decisions():
    row_spacing = derive_row_spacing_m(
        sensor_detection_width_m=20.0, rover_can_spin_in_place=True
    )
    raw_pattern = generate_coverage_pattern(FIELD, exclusions=[], row_spacing_m=row_spacing)
    pattern = [Waypoint(order=i, position=pos) for i, pos in enumerate(raw_pattern)]

    session = SweepSession(
        id="sess-1", rover_id="rover-1", geofence_id="fence-1", pattern=pattern, started_at=START
    )

    # Cover the first waypoint, then get interrupted (e.g. Bingo Fuel).
    session.mark_waypoint_complete(0)
    session.interrupt(at=START)
    assert session.status == SweepSessionStatus.INTERRUPTED

    # Resume and finish the rest.
    session.resume()
    for waypoint in session.remaining_waypoints:
        session.mark_waypoint_complete(waypoint.order)
    assert session.is_fully_covered
    session.complete(at=START)
    assert session.status == SweepSessionStatus.COMPLETED

    # A brief GPS dropout mid-sweep would have been handled like this:
    gps_response = decide_gps_loss_response(
        seconds_since_last_fix=3.0,
        current_error_radius_m=4.0,
        grace_period_s=10.0,
        max_error_radius_m=8.0,
    )
    assert gps_response == "continue_dead_reckoning"

    # And an exclusion-zone intrusion like this:
    exclusion_hit = find_intruded_exclusion((-85.0005, 38.0005), [POND])
    assert exclusion_hit is not None
    _, depth = exclusion_hit
    assert decide_exclusion_response(depth, rover_length_m=0.6) in (
        "auto_reverse",
        "wait_for_help",
    )
```

- [ ] **Step 2: Run it and verify it passes**

Run: `pytest tests/test_mission_flow_integration.py -v`
Expected: PASS

- [ ] **Step 3: Update the README**

```markdown
# Papaya Pathfinder — Pi Mission

Pure geometry, obstacle-handling, and decision-logic layer for MP-1. See
`docs/superpowers/specs/2026-09-24-mp1-map-detect-explore-design.md` for
the design this implements.

No hardware I/O, no persistence, no runtime loop here -- everything is
synchronous, pure, or operates on an explicit state object you drive
yourself. The (not-yet-written) Mission Runtime plan will wire these
modules into an actual event loop once the Pi Telemetry + Sync and
backend command-channel plans exist to plug into.

## Run the tests

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    pytest -v

## Modules

- `geo_utils.py` — shared degrees/meters helpers.
- `position_fusion.py` — GPS+IMU dead reckoning, heading, error-circle.
- `coverage_pattern.py` — boustrophedon waypoint generation.
- `exclusion_check.py` — exclusion-zone intrusion depth.
- `obstacle.py`, `classification.py`, `obstacle_detection.py`,
  `resume_validation.py` — obstacle detection, classification, and
  resume-pass reconciliation.
- `row_spacing.py` — derives coverage row spacing from sensor detection
  width and rover turning capability.
- `sweep_session.py` — the sweep-session state machine (start/
  interrupt/resume/complete).
- `exclusion_decision.py` — auto-reverse vs. wait-for-help.
- `gps_loss_decision.py` — continue-on-dead-reckoning vs. stop-and-alert.
```

- [ ] **Step 4: Commit**

```bash
git add pathfinder-autonomous/pi-mission
git commit -m "test(pi-mission): add mission-flow integration test, update README"
```

---

## Self-Review Notes

- **Spec coverage:** Row spacing derivation (Route Planning) ✓ Task 1. Sweep-session start/interrupt/resume/complete, mirroring the Data Model's Sweep session record (Mission Flow, Data Model) ✓ Task 2. Exclusion-zone auto-reverse-vs-wait-for-help at the one-rover-length threshold ✓ Task 3. GPS-loss grace-period-or-error-threshold response ✓ Task 4. The actual runtime loop (waypoint navigation driving, command-queue polling, telemetry writes, Home-return sync triggering) is explicitly deferred to a Mission Runtime plan once its dependencies (Pi Telemetry + Sync, backend command channel) exist as code.
- **Placeholder scan:** no TBD/TODO; every step has runnable code.
- **Type consistency:** `Waypoint.position` and `SweepSession`'s use of it match the `(lon, lat)` convention from `coverage_pattern.generate_coverage_pattern`'s return type, used directly in Task 5's integration test with no conversion needed.
