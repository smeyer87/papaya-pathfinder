# MP-1 Obstacle Detection & Classification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn raw sensor detections (ultrasonic relative-bearing/range + camera classification, or a bump contact) into `Obstacle` records with a correctly computed absolute position, a permanent/temporary classification, and the resume-validation logic that reconciles previously known obstacles against freshly re-detected ones.

**Architecture:** Extends the `papaya_mission` package from the Position & Coverage Geometry plan. Starts with a small refactor — extracting the shared degrees/meters math both plans need into `geo_utils.py`, and adding heading-tracking to `PositionEstimate` (a real gap in the prior plan: obstacle placement needs the rover's own compass heading, not just its lat/lon) — then adds the obstacle domain model and three pure-logic modules (classification, detection-to-obstacle conversion, resume-validation reconciliation). Camera classification results and bump-contact events are plain input data here, same as GPS/IMU readings in the prior plan — no real hardware or ML model integration in this plan.

**Tech Stack:** Python 3.11, Shapely 2.x (already a dependency), pytest. No new dependencies.

## Global Constraints

- Extends `pathfinder-autonomous/pi-mission/` from the prior plan — same package, same stack.
- Task 1 refactors already-committed code (`position_fusion.py`, `coverage_pattern.py`, `exclusion_check.py`, and their tests). The full existing test suite must pass before any new work proceeds — a regression safety net for the mechanical parts of the refactor. Task 1 also *adds* real new behavior (heading tracking, input validation) with its own TDD cycle, not folded silently into "refactor."
- **Time handling:** `GpsFix`/`ImuReading`/`PositionEstimate.timestamp` are monotonic seconds (e.g. `time.monotonic()`), used only for computing reliable elapsed-time deltas in the dead-reckoning math — never wall-clock time, which can jump on an NTP sync. `Obstacle.first_detected_at`/`last_confirmed_at` and the `detected_at`/`now` parameters throughout this plan are real `datetime` objects (UTC) — record-keeping timestamps meant to be logged, compared, and eventually synced.
- **Bearing convention:** ultrasonic/camera detections report a bearing *relative to the rover's own heading* (0 = straight ahead) — the mast rotates independently of the chassis. Converting that to an absolute compass bearing for position projection requires combining it with the rover's current heading (`rover_position.heading_deg + relative_bearing_deg`, mod 360). Getting this wrong silently places obstacles at the wrong location whenever the rover isn't facing due north — a real bug the code in this plan fixes.
- Low-confidence classifications (`confidence < 0.5`) never get promoted to `permanent-pending`, regardless of type match. (Design spec: Testing — "Malformed/low-confidence classification.")
- Bump-contact detections always get `status="permanent-pending"` — there's no type classification to lean on, so it's routed to human review rather than silently logged as temporary. This is deliberately different from a low-confidence *camera* reading, which is more likely sensor noise and stays temporary. (Design spec: Mission Flow — Bump contact.)
- Obstacle position uncertainty is inherited from the rover's current error-circle radius (from the position-fusion plan); sensor-specific range/bearing noise isn't modeled separately for v1.
- This plan produces `Obstacle` value objects only — no persistence, no sync, no sweep-session orchestration. Those are later plans that import from here.

---

## File Structure

```
pathfinder-autonomous/
  pi-mission/
    papaya_mission/
      geo_utils.py            # NEW -- shared degrees/meters helpers
      position_fusion.py       # MODIFIED -- geo_utils, heading tracking, input validation
      coverage_pattern.py       # MODIFIED -- uses geo_utils's constant
      exclusion_check.py         # MODIFIED -- uses geo_utils's constant
      obstacle.py                 # NEW -- Obstacle dataclass
      classification.py            # NEW -- classify_permanence()
      obstacle_detection.py         # NEW -- detection -> Obstacle conversion
      resume_validation.py           # NEW -- reconcile_obstacles()
    tests/
      test_geo_utils.py         # NEW
      test_position_fusion.py    # MODIFIED -- new heading/validation tests added
      test_obstacle.py            # NEW
      test_classification.py       # NEW
      test_obstacle_detection.py    # NEW
      test_resume_validation.py      # NEW
      test_obstacle_integration.py    # NEW
```

---

### Task 1: Shared geometry helpers, heading tracking, and input validation

**Files:**
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/geo_utils.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_geo_utils.py`
- Modify: `pathfinder-autonomous/pi-mission/papaya_mission/position_fusion.py`
- Modify: `pathfinder-autonomous/pi-mission/tests/test_position_fusion.py`
- Modify: `pathfinder-autonomous/pi-mission/papaya_mission/coverage_pattern.py`
- Modify: `pathfinder-autonomous/pi-mission/papaya_mission/exclusion_check.py`

**Interfaces:**
- Produces: `papaya_mission.geo_utils.{METERS_PER_DEGREE_LAT, project_position(lat, lon, bearing_deg, distance_m) -> (lat, lon), flat_earth_distance_m(a, b) -> float}` where `a`/`b` are `(lon, lat)` tuples. `PositionEstimate` gains a `heading_deg: float` field (the rover's current compass heading — needed by Task 4 to convert a mast-relative bearing into an absolute one). `PositionFusion.__init__` gains an `initial_heading_deg: float = 0.0` keyword parameter; heading updates on every `on_imu_reading` call and is untouched by `on_gps_fix`. `GpsFix`/`ImuReading` now validate their inputs in `__post_init__`, raising `ValueError` on bad data instead of silently accepting it.

- [ ] **Step 1: Write the failing tests for the new geo_utils helpers**

```python
# pathfinder-autonomous/pi-mission/tests/test_geo_utils.py
import math

from papaya_mission.geo_utils import flat_earth_distance_m, project_position


def test_project_position_north_increases_latitude():
    new_lat, new_lon = project_position(lat=38.0, lon=-85.0, bearing_deg=0.0, distance_m=100.0)

    assert new_lat > 38.0
    assert math.isclose(new_lon, -85.0, abs_tol=1e-9)


def test_project_position_east_increases_longitude():
    new_lat, new_lon = project_position(lat=38.0, lon=-85.0, bearing_deg=90.0, distance_m=100.0)

    assert math.isclose(new_lat, 38.0, abs_tol=1e-9)
    assert new_lon > -85.0


def test_project_position_zero_distance_is_a_no_op():
    new_lat, new_lon = project_position(lat=38.0, lon=-85.0, bearing_deg=45.0, distance_m=0.0)

    assert new_lat == 38.0
    assert new_lon == -85.0


def test_flat_earth_distance_between_identical_points_is_zero():
    assert flat_earth_distance_m((-85.0, 38.0), (-85.0, 38.0)) == 0.0


def test_flat_earth_distance_roughly_matches_meters_per_degree():
    distance = flat_earth_distance_m((-85.0, 38.0), (-85.0, 39.0))  # 1 degree of latitude

    assert math.isclose(distance, 111_320.0, rel_tol=0.01)
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_geo_utils.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'papaya_mission.geo_utils'`

- [ ] **Step 3: Write `geo_utils.py`**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/geo_utils.py
"""Shared geometry helpers used across the position/coverage/obstacle
modules. Flat-earth degrees<->meters approximation throughout -- fine at
the scale of a single geofenced field (see each module's own docstring
for where this assumption originates).
"""
from __future__ import annotations

import math

METERS_PER_DEGREE_LAT = 111_320.0


def project_position(
    lat: float, lon: float, bearing_deg: float, distance_m: float
) -> tuple[float, float]:
    """Project a (lat, lon) point `distance_m` meters along `bearing_deg`
    (0 = north, clockwise positive). Returns (new_lat, new_lon). This is
    an ABSOLUTE compass bearing -- callers with a mast-relative bearing
    must combine it with the rover's own heading first (see
    obstacle_detection.py).
    """
    bearing_rad = math.radians(bearing_deg)
    new_lat = lat + (distance_m * math.cos(bearing_rad)) / METERS_PER_DEGREE_LAT
    new_lon = lon + (distance_m * math.sin(bearing_rad)) / (
        METERS_PER_DEGREE_LAT * math.cos(math.radians(lat))
    )
    return new_lat, new_lon


def flat_earth_distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Approximate distance in meters between two (lon, lat) points."""
    lon1, lat1 = a
    lon2, lat2 = b
    mean_lat_rad = math.radians((lat1 + lat2) / 2)
    dlat_m = (lat2 - lat1) * METERS_PER_DEGREE_LAT
    dlon_m = (lon2 - lon1) * METERS_PER_DEGREE_LAT * math.cos(mean_lat_rad)
    return math.hypot(dlat_m, dlon_m)
```

- [ ] **Step 4: Run the new tests and verify they pass**

Run: `pytest tests/test_geo_utils.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Write failing tests for heading tracking and input validation, appended to `test_position_fusion.py`**

These test behavior `position_fusion.py` doesn't have yet — heading wasn't tracked at all, and `GpsFix`/`ImuReading` accepted any input silently.

```python
# pathfinder-autonomous/pi-mission/tests/test_position_fusion.py
import math

import pytest

from papaya_mission.position_fusion import GpsFix, ImuReading, PositionFusion


def test_seeding_with_gps_fix_sets_initial_estimate():
    fix = GpsFix(lat=38.0, lon=-85.0, accuracy_m=2.0, timestamp=0.0)

    fusion = PositionFusion(fix)

    estimate = fusion.current_estimate
    assert estimate.lat == 38.0
    assert estimate.lon == -85.0
    assert estimate.error_radius_m == 2.0


def test_imu_reading_moves_position_and_grows_error_radius():
    fix = GpsFix(lat=38.0, lon=-85.0, accuracy_m=2.0, timestamp=0.0)
    fusion = PositionFusion(fix, drift_rate_m_per_s=0.5)

    estimate = fusion.on_imu_reading(
        ImuReading(heading_deg=0.0, forward_acceleration_mps2=1.0, timestamp=1.0)
    )

    assert estimate.lat > 38.0
    assert math.isclose(estimate.lon, -85.0, abs_tol=1e-9)
    assert estimate.error_radius_m > 2.0


def test_error_radius_grows_monotonically_across_multiple_imu_readings():
    fix = GpsFix(lat=38.0, lon=-85.0, accuracy_m=2.0, timestamp=0.0)
    fusion = PositionFusion(fix, drift_rate_m_per_s=0.5)

    r1 = fusion.on_imu_reading(
        ImuReading(heading_deg=90.0, forward_acceleration_mps2=0.5, timestamp=1.0)
    ).error_radius_m
    r2 = fusion.on_imu_reading(
        ImuReading(heading_deg=90.0, forward_acceleration_mps2=0.5, timestamp=2.0)
    ).error_radius_m

    assert r2 > r1


def test_new_gps_fix_resets_error_radius_and_position():
    fix = GpsFix(lat=38.0, lon=-85.0, accuracy_m=2.0, timestamp=0.0)
    fusion = PositionFusion(fix, drift_rate_m_per_s=0.5)
    fusion.on_imu_reading(
        ImuReading(heading_deg=90.0, forward_acceleration_mps2=2.0, timestamp=5.0)
    )

    corrected = fusion.on_gps_fix(
        GpsFix(lat=38.001, lon=-85.001, accuracy_m=1.5, timestamp=6.0)
    )

    assert corrected.lat == 38.001
    assert corrected.lon == -85.001
    assert corrected.error_radius_m == 1.5


def test_zero_or_negative_dt_is_ignored():
    fix = GpsFix(lat=38.0, lon=-85.0, accuracy_m=2.0, timestamp=5.0)
    fusion = PositionFusion(fix)

    estimate = fusion.on_imu_reading(
        ImuReading(heading_deg=0.0, forward_acceleration_mps2=5.0, timestamp=5.0)
    )

    assert estimate.lat == 38.0
    assert estimate.lon == -85.0


def test_heading_deg_updates_with_imu_readings():
    fix = GpsFix(lat=38.0, lon=-85.0, accuracy_m=2.0, timestamp=0.0)
    fusion = PositionFusion(fix, initial_heading_deg=45.0)

    assert fusion.current_estimate.heading_deg == 45.0

    estimate = fusion.on_imu_reading(
        ImuReading(heading_deg=270.0, forward_acceleration_mps2=0.0, timestamp=1.0)
    )

    assert estimate.heading_deg == 270.0


def test_gps_fix_does_not_change_heading():
    fix = GpsFix(lat=38.0, lon=-85.0, accuracy_m=2.0, timestamp=0.0)
    fusion = PositionFusion(fix, initial_heading_deg=45.0)
    fusion.on_imu_reading(
        ImuReading(heading_deg=90.0, forward_acceleration_mps2=0.0, timestamp=1.0)
    )

    corrected = fusion.on_gps_fix(
        GpsFix(lat=38.001, lon=-85.001, accuracy_m=1.5, timestamp=2.0)
    )

    assert corrected.heading_deg == 90.0  # unchanged by the GPS fix


def test_imu_reading_rejects_heading_out_of_range():
    with pytest.raises(ValueError):
        ImuReading(heading_deg=360.0, forward_acceleration_mps2=0.0, timestamp=0.0)
    with pytest.raises(ValueError):
        ImuReading(heading_deg=-1.0, forward_acceleration_mps2=0.0, timestamp=0.0)


def test_gps_fix_rejects_negative_accuracy():
    with pytest.raises(ValueError):
        GpsFix(lat=38.0, lon=-85.0, accuracy_m=-1.0, timestamp=0.0)
```

- [ ] **Step 6: Run `test_position_fusion.py` and verify the new tests fail, old ones still pass**

Run: `pytest tests/test_position_fusion.py -v`
Expected: the 5 original tests PASS unchanged; `test_heading_deg_updates_with_imu_readings`, `test_gps_fix_does_not_change_heading`, `test_imu_reading_rejects_heading_out_of_range`, and `test_gps_fix_rejects_negative_accuracy` FAIL (`AttributeError: 'PositionEstimate' object has no attribute 'heading_deg'` / no exception raised for bad input).

- [ ] **Step 7: Rewrite `position_fusion.py`** — geo_utils refactor, heading tracking, and validation together, since all three touch the same file

```python
# pathfinder-autonomous/pi-mission/papaya_mission/position_fusion.py
"""GPS+IMU dead-reckoning position fusion with a growing error-circle
uncertainty radius. See design spec: Architecture -- Positioning.

Deliberately simple: forward-acceleration-only IMU model (not full 3-axis
inertial fusion), flat-earth degrees<->meters approximation (fine at the
scale of a single geofenced field). No wheel encoders -- velocity comes
from integrating accelerometer readings, which drifts, which is exactly
why the error circle exists and why it resets at every GPS fix.

`timestamp` fields are monotonic seconds (e.g. time.monotonic() on the
real Pi), not wall-clock time -- this module only needs reliable
elapsed-time deltas between readings, and wall-clock time can jump on an
NTP sync, which would corrupt the dead-reckoning math. Wall-clock
timestamps for records (e.g. Obstacle.first_detected_at) are a separate
concern, tracked by the caller.
"""
from __future__ import annotations

from dataclasses import dataclass

from papaya_mission.geo_utils import project_position


@dataclass
class GpsFix:
    lat: float
    lon: float
    accuracy_m: float
    timestamp: float  # monotonic seconds

    def __post_init__(self) -> None:
        if self.accuracy_m < 0:
            raise ValueError(f"accuracy_m must be >= 0, got {self.accuracy_m}")


@dataclass
class ImuReading:
    heading_deg: float  # compass heading, 0 = north, clockwise positive
    forward_acceleration_mps2: float
    timestamp: float  # monotonic seconds

    def __post_init__(self) -> None:
        if not (0.0 <= self.heading_deg < 360.0):
            raise ValueError(f"heading_deg must be in [0, 360), got {self.heading_deg}")


@dataclass
class PositionEstimate:
    lat: float
    lon: float
    heading_deg: float
    error_radius_m: float
    timestamp: float


class PositionFusion:
    def __init__(
        self,
        initial_fix: GpsFix,
        initial_heading_deg: float = 0.0,
        drift_rate_m_per_s: float = 0.5,
    ):
        self._lat = initial_fix.lat
        self._lon = initial_fix.lon
        self._heading_deg = initial_heading_deg
        self._error_radius_m = initial_fix.accuracy_m
        self._velocity_mps = 0.0
        self._last_timestamp = initial_fix.timestamp
        self._drift_rate_m_per_s = drift_rate_m_per_s

    @property
    def current_estimate(self) -> PositionEstimate:
        return PositionEstimate(
            lat=self._lat,
            lon=self._lon,
            heading_deg=self._heading_deg,
            error_radius_m=self._error_radius_m,
            timestamp=self._last_timestamp,
        )

    def on_gps_fix(self, fix: GpsFix) -> PositionEstimate:
        self._lat = fix.lat
        self._lon = fix.lon
        self._error_radius_m = fix.accuracy_m
        self._velocity_mps = 0.0
        self._last_timestamp = fix.timestamp
        return self.current_estimate

    def on_imu_reading(self, reading: ImuReading) -> PositionEstimate:
        dt = reading.timestamp - self._last_timestamp
        if dt <= 0:
            return self.current_estimate

        self._velocity_mps += reading.forward_acceleration_mps2 * dt
        distance_m = self._velocity_mps * dt

        self._lat, self._lon = project_position(
            self._lat, self._lon, reading.heading_deg, distance_m
        )
        self._heading_deg = reading.heading_deg

        self._error_radius_m += self._drift_rate_m_per_s * dt
        self._last_timestamp = reading.timestamp

        return self.current_estimate
```

- [ ] **Step 8: Run `test_position_fusion.py` and verify all 9 tests pass**

Run: `pytest tests/test_position_fusion.py -v`
Expected: PASS (9 passed)

- [ ] **Step 9: Refactor `coverage_pattern.py` to use `geo_utils`'s constant**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/coverage_pattern.py
"""Boustrophedon (lawnmower) coverage-pattern generation over a geofence,
avoiding exclusion zones. Deliberately simple per the design spec's Route
Planning notes -- open fields, gentle slopes, no road-network routing.
"""
from __future__ import annotations

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from papaya_mission.geo_utils import METERS_PER_DEGREE_LAT


def generate_coverage_pattern(
    inclusive: Polygon,
    exclusions: list[Polygon],
    row_spacing_m: float,
) -> list[tuple[float, float]]:
    """Generate an ordered lawnmower waypoint path covering `inclusive`
    while avoiding `exclusions`. Returns [(lon, lat), ...].
    """
    allowed_area = inclusive
    if exclusions:
        allowed_area = inclusive.difference(unary_union(exclusions))

    if allowed_area.is_empty:
        return []

    minx, miny, maxx, maxy = inclusive.bounds
    row_spacing_deg = row_spacing_m / METERS_PER_DEGREE_LAT

    waypoints: list[tuple[float, float]] = []
    row_index = 0
    lat = miny + row_spacing_deg / 2

    while lat <= maxy:
        row_line = LineString([(minx, lat), (maxx, lat)])
        intersection = allowed_area.intersection(row_line)

        segments = _as_line_segments(intersection)
        if row_index % 2 == 1:
            segments = [segment[::-1] for segment in reversed(segments)]

        for segment in segments:
            waypoints.extend(segment)

        lat += row_spacing_deg
        row_index += 1

    return waypoints


def _as_line_segments(geometry) -> list[list[tuple[float, float]]]:
    if geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [list(geometry.coords)]
    if geometry.geom_type == "MultiLineString":
        return [list(line.coords) for line in geometry.geoms]
    if geometry.geom_type == "Point":
        return []
    raise ValueError(
        f"unexpected row/allowed-area intersection type: {geometry.geom_type} "
        "-- likely a complex exclusion shape; extend this function to handle it"
    )
```

- [ ] **Step 10: Refactor `exclusion_check.py` to use `geo_utils`'s constant**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/exclusion_check.py
"""Exclusion-zone intrusion depth checks. Supports the design spec's
Mission Flow rule: under one rover-length and easily reversible ->
auto-reverse, otherwise stop and wait for help. This module only
computes the geometric depth; the auto-reverse-vs-wait-for-help decision
belongs to the mission-flow state machine that calls it.
"""
from __future__ import annotations

from shapely.geometry import Point, Polygon

from papaya_mission.geo_utils import METERS_PER_DEGREE_LAT


def exclusion_intrusion_depth_m(
    position: tuple[float, float], exclusion: Polygon
) -> float | None:
    """How many meters `position` (lon, lat) is inside `exclusion`, or
    None if it's outside. Flat-earth degrees-to-meters approximation --
    fine at the scale of a single geofenced field.
    """
    point = Point(position)
    if not exclusion.contains(point):
        return None
    degrees_to_boundary = exclusion.exterior.distance(point)
    return degrees_to_boundary * METERS_PER_DEGREE_LAT


def find_intruded_exclusion(
    position: tuple[float, float], exclusions: list[Polygon]
) -> tuple[Polygon, float] | None:
    """(exclusion_polygon, intrusion_depth_m) for the first exclusion zone
    `position` is inside, or None if outside all of them.
    """
    for exclusion in exclusions:
        depth = exclusion_intrusion_depth_m(position, exclusion)
        if depth is not None:
            return exclusion, depth
    return None
```

- [ ] **Step 11: Run the full test suite and verify zero regressions**

Run: `pytest -v`
Expected: PASS — `test_geo_utils.py` (5), `test_position_fusion.py` (9), `test_coverage_pattern.py` (4), `test_exclusion_check.py` (5), `test_integration.py` (2) all pass. If anything outside `test_position_fusion.py` fails, the `geo_utils` extraction changed behavior — stop and diagnose before continuing.

- [ ] **Step 12: Commit**

```bash
git add pathfinder-autonomous/pi-mission
git commit -m "refactor(pi-mission): extract geo_utils, add heading tracking and input validation"
```

---

### Task 2: Obstacle domain model

**Files:**
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/obstacle.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_obstacle.py`

**Interfaces:**
- Produces: `papaya_mission.obstacle.Obstacle` — frozen dataclass with `position: tuple[float, float]` (lon, lat), `position_uncertainty_m: float`, `type: str`, `classification_confidence: float`, `detection_method: Literal["ultrasonic+camera", "contact-only"]`, `status: Literal["temporary", "permanent-pending"]`, `first_detected_at: datetime`, `last_confirmed_at: datetime | None = None`. Used by Tasks 4 and 5, and by the later Pi-telemetry-and-sync plan when persisting to the local store. Deliberately excludes lifecycle fields (`id`, `review_status`, `reviewed_by`, `reviewed_at`, `synced_at`) owned by that later plan.

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_obstacle.py
import dataclasses
from datetime import datetime, timezone

import pytest

from papaya_mission.obstacle import Obstacle

DETECTED_AT = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


def test_obstacle_is_constructible():
    obstacle = Obstacle(
        position=(-85.0005, 38.0005),
        position_uncertainty_m=2.0,
        type="barrel",
        classification_confidence=0.9,
        detection_method="ultrasonic+camera",
        status="permanent-pending",
        first_detected_at=DETECTED_AT,
    )

    assert obstacle.type == "barrel"
    assert obstacle.last_confirmed_at is None


def test_obstacle_is_immutable():
    obstacle = Obstacle(
        position=(-85.0005, 38.0005),
        position_uncertainty_m=2.0,
        type="barrel",
        classification_confidence=0.9,
        detection_method="ultrasonic+camera",
        status="permanent-pending",
        first_detected_at=DETECTED_AT,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        obstacle.type = "chair"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_obstacle.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'papaya_mission.obstacle'`

- [ ] **Step 3: Write the implementation**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/obstacle.py
"""The obstacle detection domain object. Mirrors the fields the backend's
Obstacle record needs (design spec: Data Model -- Obstacle record) that
this plan's logic actually determines. Persistence-lifecycle fields (id,
review_status, reviewed_by, reviewed_at, synced_at) are owned by the
Pi-telemetry-and-sync plan and the backend review workflow, not here.

Timestamp fields are real (wall-clock, UTC) datetimes -- unlike
position_fusion.py's monotonic-seconds timestamps, these are
record-keeping values meant to be logged, compared, and eventually
synced.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

DetectionMethod = Literal["ultrasonic+camera", "contact-only"]
ObstacleStatus = Literal["temporary", "permanent-pending"]


@dataclass(frozen=True)
class Obstacle:
    position: tuple[float, float]  # (lon, lat)
    position_uncertainty_m: float
    type: str
    classification_confidence: float
    detection_method: DetectionMethod
    status: ObstacleStatus
    first_detected_at: datetime
    last_confirmed_at: datetime | None = None
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_obstacle.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/obstacle.py pathfinder-autonomous/pi-mission/tests/test_obstacle.py
git commit -m "feat(pi-mission): add Obstacle domain model"
```

---

### Task 3: Permanent/temporary classification heuristic

**Files:**
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/classification.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_classification.py`

**Interfaces:**
- Consumes: nothing from earlier tasks in this plan.
- Produces: `papaya_mission.classification.{LOW_CONFIDENCE_THRESHOLD, classify_permanence(classified_type: str, confidence: float) -> Literal["temporary", "permanent-pending"]}`, raising `ValueError` if `confidence` is outside `[0, 1]`. Used by Task 4's `obstacle_from_ultrasonic_camera_detection`.

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_classification.py
import pytest

from papaya_mission.classification import LOW_CONFIDENCE_THRESHOLD, classify_permanence


def test_permanent_type_high_confidence_is_permanent_pending():
    assert classify_permanence("barrel", confidence=0.9) == "permanent-pending"


def test_temporary_type_high_confidence_is_temporary():
    assert classify_permanence("chair", confidence=0.9) == "temporary"


def test_permanent_type_low_confidence_is_not_promoted():
    assert classify_permanence("barrel", confidence=0.2) == "temporary"


def test_unrecognized_type_defaults_to_temporary():
    assert classify_permanence("mystery_object", confidence=0.95) == "temporary"


def test_confidence_exactly_at_threshold_is_not_low_confidence():
    assert classify_permanence("fence_post", confidence=LOW_CONFIDENCE_THRESHOLD) == "permanent-pending"


def test_confidence_out_of_range_raises():
    with pytest.raises(ValueError):
        classify_permanence("barrel", confidence=1.5)
    with pytest.raises(ValueError):
        classify_permanence("barrel", confidence=-0.1)
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_classification.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'papaya_mission.classification'`

- [ ] **Step 3: Write the implementation**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/classification.py
"""Maps a camera-classified type + confidence to a permanent/temporary
obstacle status. See design spec: Mission Flow -- Detection (the type
heuristic: barrel/post/fence -> permanent-candidate; chair/vehicle ->
temporary) and Testing -- Malformed/low-confidence classification.
"""
from __future__ import annotations

from typing import Literal

LOW_CONFIDENCE_THRESHOLD = 0.5

_PERMANENT_TYPES = {"barrel", "utility_pole", "fence_post"}


def classify_permanence(
    classified_type: str, confidence: float
) -> Literal["temporary", "permanent-pending"]:
    """A low-confidence classification never gets promoted to
    permanent-pending, regardless of type match -- a wrong permanent tag
    pollutes the shared map more than a wrong temporary tag, which
    simply isn't carried forward. Anything not in the known permanent
    set (recognized temporary types and unrecognized/novel ones alike)
    defaults to temporary.
    """
    if not (0.0 <= confidence <= 1.0):
        raise ValueError(f"confidence must be in [0, 1], got {confidence}")
    if confidence < LOW_CONFIDENCE_THRESHOLD:
        return "temporary"
    if classified_type in _PERMANENT_TYPES:
        return "permanent-pending"
    return "temporary"
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_classification.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/classification.py pathfinder-autonomous/pi-mission/tests/test_classification.py
git commit -m "feat(pi-mission): add permanent/temporary classification heuristic"
```

---

### Task 4: Detection-to-obstacle conversion

**Files:**
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/obstacle_detection.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_obstacle_detection.py`

**Interfaces:**
- Consumes: `papaya_mission.geo_utils.project_position` (Task 1), `papaya_mission.classification.classify_permanence` (Task 3), `papaya_mission.obstacle.Obstacle` (Task 2), `papaya_mission.position_fusion.PositionEstimate` (Task 1 — now including `heading_deg`).
- Produces: `papaya_mission.obstacle_detection.{obstacle_from_ultrasonic_camera_detection(rover_position, relative_bearing_deg, range_m, classified_type, classification_confidence, detected_at: datetime) -> Obstacle, obstacle_from_bump_contact(rover_position, detected_at: datetime) -> Obstacle}`. Note the parameter is `relative_bearing_deg`, not `bearing_deg` — it's the mast's angle relative to the rover's own heading, combined internally with `rover_position.heading_deg` before projecting. The mission-flow state machine plan calls these whenever a sensor reports a detection.

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_obstacle_detection.py
import math
from datetime import datetime, timezone

from papaya_mission.obstacle_detection import (
    obstacle_from_bump_contact,
    obstacle_from_ultrasonic_camera_detection,
)
from papaya_mission.position_fusion import PositionEstimate

DETECTED_AT = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)

# Rover facing east (heading 90) -- deliberately non-north so these tests
# actually exercise the relative-bearing + heading combination instead of
# accidentally passing with heading silently treated as zero.
ROVER_POSITION = PositionEstimate(
    lat=38.0, lon=-85.0, heading_deg=90.0, error_radius_m=1.5, timestamp=10.0
)


def test_relative_bearing_zero_combines_with_rover_heading():
    # Straight ahead (relative bearing 0) while facing east should place
    # the obstacle east of the rover, not north.
    obstacle = obstacle_from_ultrasonic_camera_detection(
        rover_position=ROVER_POSITION,
        relative_bearing_deg=0.0,
        range_m=10.0,
        classified_type="barrel",
        classification_confidence=0.9,
        detected_at=DETECTED_AT,
    )

    obstacle_lon, obstacle_lat = obstacle.position
    assert obstacle_lon > ROVER_POSITION.lon
    assert math.isclose(obstacle_lat, ROVER_POSITION.lat, abs_tol=1e-6)


def test_relative_bearing_offsets_from_rover_heading():
    # Mast turned 270 degrees relative to the chassis while facing east
    # (heading 90) works out to absolute bearing 0 (north): 90+270=360=0.
    obstacle = obstacle_from_ultrasonic_camera_detection(
        rover_position=ROVER_POSITION,
        relative_bearing_deg=270.0,
        range_m=10.0,
        classified_type="barrel",
        classification_confidence=0.9,
        detected_at=DETECTED_AT,
    )

    obstacle_lon, obstacle_lat = obstacle.position
    assert obstacle_lat > ROVER_POSITION.lat
    assert math.isclose(obstacle_lon, ROVER_POSITION.lon, abs_tol=1e-6)


def test_obstacle_type_status_and_uncertainty_still_set_correctly():
    obstacle = obstacle_from_ultrasonic_camera_detection(
        rover_position=ROVER_POSITION,
        relative_bearing_deg=0.0,
        range_m=10.0,
        classified_type="barrel",
        classification_confidence=0.9,
        detected_at=DETECTED_AT,
    )

    assert obstacle.type == "barrel"
    assert obstacle.status == "permanent-pending"
    assert obstacle.detection_method == "ultrasonic+camera"
    assert obstacle.position_uncertainty_m == ROVER_POSITION.error_radius_m
    assert obstacle.first_detected_at == DETECTED_AT


def test_ultrasonic_camera_detection_low_confidence_stays_temporary():
    obstacle = obstacle_from_ultrasonic_camera_detection(
        rover_position=ROVER_POSITION,
        relative_bearing_deg=0.0,
        range_m=10.0,
        classified_type="barrel",
        classification_confidence=0.1,
        detected_at=DETECTED_AT,
    )

    assert obstacle.status == "temporary"


def test_bump_contact_is_always_permanent_pending_and_unknown_type():
    obstacle = obstacle_from_bump_contact(rover_position=ROVER_POSITION, detected_at=DETECTED_AT)

    assert obstacle.type == "unknown"
    assert obstacle.status == "permanent-pending"
    assert obstacle.detection_method == "contact-only"
    assert obstacle.position == (ROVER_POSITION.lon, ROVER_POSITION.lat)
    assert obstacle.first_detected_at == DETECTED_AT
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_obstacle_detection.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'papaya_mission.obstacle_detection'`

- [ ] **Step 3: Write the implementation**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/obstacle_detection.py
"""Converts raw sensor detections into Obstacle records, using the fused
position estimate for absolute placement. See design spec: Mission Flow
-- Execution loop (Detection, Bump contact).
"""
from __future__ import annotations

from datetime import datetime

from papaya_mission.classification import classify_permanence
from papaya_mission.geo_utils import project_position
from papaya_mission.obstacle import Obstacle
from papaya_mission.position_fusion import PositionEstimate


def obstacle_from_ultrasonic_camera_detection(
    rover_position: PositionEstimate,
    relative_bearing_deg: float,
    range_m: float,
    classified_type: str,
    classification_confidence: float,
    detected_at: datetime,
) -> Obstacle:
    """`relative_bearing_deg` is the ultrasonic/camera mast's angle
    relative to the rover's own heading (0 = straight ahead) -- the mast
    rotates independently of the chassis, so the detected object may not
    be dead ahead. Combined with the rover's current compass heading
    (from the fused position estimate) to get the absolute bearing the
    obstacle actually sits at before projecting outward by `range_m`.
    """
    absolute_bearing_deg = (rover_position.heading_deg + relative_bearing_deg) % 360.0

    obstacle_lat, obstacle_lon = project_position(
        rover_position.lat, rover_position.lon, absolute_bearing_deg, range_m
    )
    status = classify_permanence(classified_type, classification_confidence)

    return Obstacle(
        position=(obstacle_lon, obstacle_lat),
        position_uncertainty_m=rover_position.error_radius_m,
        type=classified_type,
        classification_confidence=classification_confidence,
        detection_method="ultrasonic+camera",
        status=status,
        first_detected_at=detected_at,
    )


def obstacle_from_bump_contact(
    rover_position: PositionEstimate,
    detected_at: datetime,
) -> Obstacle:
    """A reactive detection: something was hit that proactive sensors
    missed. The contact point is the rover's own current position -- no
    bearing/range to project, unlike a proactive ultrasonic+camera
    detection. No type classification is possible, so it's always
    flagged for human review (permanent-pending) rather than silently
    logged as temporary -- a bump contact is real, actionable
    information about a sensing gap, unlike a low-confidence camera
    reading that's more likely just noise.
    """
    return Obstacle(
        position=(rover_position.lon, rover_position.lat),
        position_uncertainty_m=rover_position.error_radius_m,
        type="unknown",
        classification_confidence=0.0,
        detection_method="contact-only",
        status="permanent-pending",
        first_detected_at=detected_at,
    )
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_obstacle_detection.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/obstacle_detection.py pathfinder-autonomous/pi-mission/tests/test_obstacle_detection.py
git commit -m "feat(pi-mission): convert sensor detections into Obstacle records"
```

---

### Task 5: Resume-validation reconciliation

**Files:**
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/resume_validation.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_resume_validation.py`

**Interfaces:**
- Consumes: `papaya_mission.geo_utils.flat_earth_distance_m` (Task 1), `papaya_mission.obstacle.Obstacle` (Task 2).
- Produces: `papaya_mission.resume_validation.{ReconciliationResult, reconcile_obstacles(known_obstacles: list[Obstacle], freshly_detected: list[Obstacle], now: datetime, match_radius_m: float = 3.0) -> ReconciliationResult}`. `ReconciliationResult` has `.confirmed` (known obstacles matched to a fresh detection, `last_confirmed_at` updated to `now`), `.cleared` (temporary, no match — caller removes these), `.discrepancies` (permanent-pending, no match — caller flags, never removes). The mission-flow state machine plan calls this during a resume pass (design spec: Mission Flow — Resume validation).

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_resume_validation.py
from datetime import datetime, timedelta, timezone

from papaya_mission.obstacle import Obstacle
from papaya_mission.resume_validation import reconcile_obstacles

FIRST_DETECTED = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
NOW = FIRST_DETECTED + timedelta(minutes=30)


def _obstacle(lon, lat, status, obstacle_type="barrel"):
    return Obstacle(
        position=(lon, lat),
        position_uncertainty_m=1.0,
        type=obstacle_type,
        classification_confidence=0.9,
        detection_method="ultrasonic+camera",
        status=status,
        first_detected_at=FIRST_DETECTED,
    )


def test_matched_obstacle_is_confirmed_with_updated_timestamp():
    known = _obstacle(-85.0, 38.0, "temporary")
    fresh = _obstacle(-85.0, 38.0, "temporary")

    result = reconcile_obstacles([known], [fresh], now=NOW)

    assert len(result.confirmed) == 1
    assert result.confirmed[0].last_confirmed_at == NOW
    assert result.confirmed[0].position == known.position
    assert result.cleared == []
    assert result.discrepancies == []


def test_missing_temporary_obstacle_is_cleared_not_flagged():
    known = _obstacle(-85.0, 38.0, "temporary")

    result = reconcile_obstacles([known], freshly_detected=[], now=NOW)

    assert result.cleared == [known]
    assert result.discrepancies == []
    assert result.confirmed == []


def test_missing_permanent_pending_obstacle_is_flagged_not_removed():
    known = _obstacle(-85.0, 38.0, "permanent-pending")

    result = reconcile_obstacles([known], freshly_detected=[], now=NOW)

    assert result.discrepancies == [known]
    assert result.cleared == []
    assert result.confirmed == []


def test_far_away_detection_does_not_count_as_a_match():
    known = _obstacle(-85.0, 38.0, "temporary")
    far_away = _obstacle(-84.0, 37.0, "temporary")  # well beyond match_radius_m

    result = reconcile_obstacles([known], [far_away], now=NOW, match_radius_m=3.0)

    assert result.cleared == [known]
    assert result.confirmed == []
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_resume_validation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'papaya_mission.resume_validation'`

- [ ] **Step 3: Write the implementation**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/resume_validation.py
"""Resume-validation obstacle reconciliation: compares previously known
obstacles against freshly re-detected ones during a resume pass. See
design spec: Mission Flow -- Resume validation.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime

from papaya_mission.geo_utils import flat_earth_distance_m
from papaya_mission.obstacle import Obstacle


@dataclass
class ReconciliationResult:
    confirmed: list[Obstacle]
    cleared: list[Obstacle]
    discrepancies: list[Obstacle]


def reconcile_obstacles(
    known_obstacles: list[Obstacle],
    freshly_detected: list[Obstacle],
    now: datetime,
    match_radius_m: float = 3.0,
) -> ReconciliationResult:
    confirmed: list[Obstacle] = []
    cleared: list[Obstacle] = []
    discrepancies: list[Obstacle] = []

    for known in known_obstacles:
        match = _find_nearby_match(known, freshly_detected, match_radius_m)
        if match is not None:
            confirmed.append(dataclasses.replace(known, last_confirmed_at=now))
        elif known.status == "temporary":
            cleared.append(known)
        else:
            discrepancies.append(known)

    return ReconciliationResult(confirmed=confirmed, cleared=cleared, discrepancies=discrepancies)


def _find_nearby_match(
    known: Obstacle, freshly_detected: list[Obstacle], match_radius_m: float
) -> Obstacle | None:
    for candidate in freshly_detected:
        if flat_earth_distance_m(known.position, candidate.position) <= match_radius_m:
            return candidate
    return None
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_resume_validation.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/resume_validation.py pathfinder-autonomous/pi-mission/tests/test_resume_validation.py
git commit -m "feat(pi-mission): add resume-validation obstacle reconciliation"
```

---

### Task 6: Integration test and README update

**Files:**
- Create: `pathfinder-autonomous/pi-mission/tests/test_obstacle_integration.py`
- Modify: `pathfinder-autonomous/pi-mission/README.md`

**Interfaces:**
- Consumes: everything from Tasks 2–5.
- Produces: nothing new — proves detection, classification, and reconciliation compose correctly end to end, and documents the additions for the mission-flow plan that comes next.

- [ ] **Step 1: Write the integration test**

```python
# pathfinder-autonomous/pi-mission/tests/test_obstacle_integration.py
from datetime import datetime, timedelta, timezone

from papaya_mission.obstacle_detection import (
    obstacle_from_bump_contact,
    obstacle_from_ultrasonic_camera_detection,
)
from papaya_mission.position_fusion import PositionEstimate
from papaya_mission.resume_validation import reconcile_obstacles

FIRST_PASS = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
RESUME_PASS = FIRST_PASS + timedelta(hours=1)


def test_sweep_then_resume_pass_reconciles_correctly():
    rover_position = PositionEstimate(
        lat=38.0, lon=-85.0, heading_deg=0.0, error_radius_m=1.5, timestamp=0.0
    )

    barrel = obstacle_from_ultrasonic_camera_detection(
        rover_position,
        relative_bearing_deg=0.0,
        range_m=5.0,
        classified_type="barrel",
        classification_confidence=0.9,
        detected_at=FIRST_PASS,
    )
    chair = obstacle_from_ultrasonic_camera_detection(
        rover_position,
        relative_bearing_deg=180.0,
        range_m=5.0,
        classified_type="chair",
        classification_confidence=0.9,
        detected_at=FIRST_PASS + timedelta(seconds=1),
    )
    known_obstacles = [barrel, chair]
    assert barrel.status == "permanent-pending"
    assert chair.status == "temporary"

    # Resume pass: the barrel is still there, the chair has been moved
    # (no longer detected), and a bump reveals something proactive
    # sensors missed entirely.
    fresh_barrel = obstacle_from_ultrasonic_camera_detection(
        rover_position,
        relative_bearing_deg=0.0,
        range_m=5.0,
        classified_type="barrel",
        classification_confidence=0.9,
        detected_at=RESUME_PASS,
    )
    bump_discovery = obstacle_from_bump_contact(
        rover_position, detected_at=RESUME_PASS + timedelta(seconds=1)
    )

    result = reconcile_obstacles(known_obstacles, [fresh_barrel], now=RESUME_PASS)

    assert len(result.confirmed) == 1
    assert result.confirmed[0].type == "barrel"
    assert result.cleared == [chair]
    assert result.discrepancies == []
    assert bump_discovery.status == "permanent-pending"  # goes into the review queue separately
```

- [ ] **Step 2: Run it and verify it passes**

Run: `pytest tests/test_obstacle_integration.py -v`
Expected: PASS

- [ ] **Step 3: Update the README**

```markdown
# Papaya Pathfinder — Pi Mission (Position & Coverage Geometry)

Pure geometry/algorithm layer for MP-1: GPS+IMU dead-reckoning position
fusion (with heading tracking and a growing error-circle), boustrophedon
coverage-pattern generation, exclusion-zone intrusion checks, and
obstacle detection/classification/resume-reconciliation. See
`docs/superpowers/specs/2026-09-24-mp1-map-detect-explore-design.md` for
the design this implements.

No hardware I/O here -- `GpsFix`/`ImuReading`/classification
results/bump events are all plain data a later sensor-driver layer will
produce from real hardware; this package only does the math and
decision logic. No persistence or orchestration either -- that's the
mission-flow state machine plan that imports these modules.

**Time handling:** `position_fusion.py`'s `timestamp` fields are
monotonic seconds (e.g. `time.monotonic()`), used only for computing
elapsed-time deltas -- never wall-clock time. Everything else
(`Obstacle.first_detected_at`, `detected_at`, `now`) is a real UTC
`datetime`.

**Bearing convention:** ultrasonic/camera detections report a bearing
relative to the rover's own heading (0 = straight ahead), not an
absolute compass bearing -- the mast rotates independently of the
chassis. `obstacle_detection.py` combines it with the rover's current
heading before placing the obstacle.

## Run the tests

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    pytest -v

## Modules

- `geo_utils.py` — shared degrees/meters helpers (`project_position`,
  `flat_earth_distance_m`) used by every other module.
- `position_fusion.py` — `PositionFusion`: seed with a `GpsFix`, feed
  `ImuReading`s between fixes, read `.current_estimate` for the fused
  position + heading + error-circle radius.
- `coverage_pattern.py` — `generate_coverage_pattern(inclusive,
  exclusions, row_spacing_m)`: ordered `(lon, lat)` lawnmower waypoints.
- `exclusion_check.py` — `find_intruded_exclusion(position,
  exclusions)`: which exclusion zone (if any) a position is inside, and
  how deep.
- `obstacle.py` — `Obstacle`: the detection domain object.
- `classification.py` — `classify_permanence(type, confidence)`: the
  permanent/temporary heuristic, with a low-confidence safety override.
- `obstacle_detection.py` — turns a sensor detection (ultrasonic+camera
  relative-bearing/range, or a bump contact) into an `Obstacle` at an
  absolute position.
- `resume_validation.py` — `reconcile_obstacles(known, fresh, now)`:
  confirms, clears, or flags-as-discrepancy previously known obstacles
  during a resume pass.
```

- [ ] **Step 4: Commit**

```bash
git add pathfinder-autonomous/pi-mission
git commit -m "test(pi-mission): add obstacle pipeline integration test, update README"
```

---

## Self-Review Notes

- **Spec coverage:** Detection (position + type + permanent/temporary tagging, now with correct absolute-bearing computation from relative bearing + rover heading) ✓ Task 4. Bump contact (immediate, always flagged for review) ✓ Task 4. Low-confidence classification never promoted ✓ Task 3. Resume validation (confirm/clear/flag-discrepancy, never silently remove permanent-candidates) ✓ Task 5. The shared geometry refactor plus heading tracking and input validation (Task 1) close gaps found in review of the prior plan. Real camera/ML model integration, real bump-sensor I2C bus reading, persistence, sync, and sweep-session orchestration are explicitly out of scope — later plans.
- **Placeholder scan:** no TBD/TODO; every step has runnable code.
- **Type consistency:** `Obstacle.position` is `(lon, lat)` everywhere it's produced (Task 4) and consumed (Task 5's `flat_earth_distance_m`), matching the GeoJSON coordinate-order convention from the backend plan. `PositionEstimate` now carries `heading_deg`, read consistently in Task 4. `datetime` is used consistently for all record-keeping timestamps (`Obstacle.first_detected_at`/`last_confirmed_at`, `detected_at`, `now`); `float` is used consistently and exclusively for monotonic-clock fields internal to `position_fusion.py`. No module mixes the two.
