# MP-1 Obstacle Detection & Classification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn raw sensor detections (ultrasonic bearing/range + camera classification, or a bump contact) into `Obstacle` records with an absolute position, a permanent/temporary classification, and the resume-validation logic that reconciles previously known obstacles against freshly re-detected ones.

**Architecture:** Extends the `papaya_mission` package from the Position & Coverage Geometry plan. Starts with a small refactor — extracting the shared degrees/meters math both plans need into `geo_utils.py` — then adds the obstacle domain model and three pure-logic modules (classification, detection-to-obstacle conversion, resume-validation reconciliation). Camera classification results and bump-contact events are plain input data here, same as GPS/IMU readings in the prior plan — no real hardware or ML model integration in this plan.

**Tech Stack:** Python 3.11, Shapely 2.x (already a dependency), pytest. No new dependencies.

## Global Constraints

- Extends `pathfinder-autonomous/pi-mission/` from the prior plan — same package, same stack.
- Task 1 refactors already-committed code (`position_fusion.py`, `coverage_pattern.py`, `exclusion_check.py`). The full existing test suite must pass with zero changes to test assertions before any new work proceeds — this is a safety-net regression check, not a behavior change.
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
      position_fusion.py       # MODIFIED -- uses geo_utils
      coverage_pattern.py       # MODIFIED -- uses geo_utils's constant
      exclusion_check.py         # MODIFIED -- uses geo_utils's constant
      obstacle.py                 # NEW -- Obstacle dataclass
      classification.py            # NEW -- classify_permanence()
      obstacle_detection.py         # NEW -- detection -> Obstacle conversion
      resume_validation.py           # NEW -- reconcile_obstacles()
    tests/
      test_geo_utils.py         # NEW
      test_obstacle.py           # NEW
      test_classification.py      # NEW
      test_obstacle_detection.py   # NEW
      test_resume_validation.py     # NEW
      test_obstacle_integration.py   # NEW
```

---

### Task 1: Extract shared geometry helpers, refactor existing modules onto them

**Files:**
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/geo_utils.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_geo_utils.py`
- Modify: `pathfinder-autonomous/pi-mission/papaya_mission/position_fusion.py`
- Modify: `pathfinder-autonomous/pi-mission/papaya_mission/coverage_pattern.py`
- Modify: `pathfinder-autonomous/pi-mission/papaya_mission/exclusion_check.py`

**Interfaces:**
- Produces: `papaya_mission.geo_utils.{METERS_PER_DEGREE_LAT, project_position(lat, lon, bearing_deg, distance_m) -> (lat, lon), flat_earth_distance_m(a, b) -> float}` where `a`/`b` are `(lon, lat)` tuples. `project_position` replaces the inline projection math `position_fusion.py` had; `flat_earth_distance_m` is new, used by Task 5's reconciliation. `position_fusion.PositionFusion`'s public behavior (from the prior plan) is unchanged — this is a pure refactor.

- [ ] **Step 1: Write the failing tests for the new helpers**

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
    (0 = north, clockwise positive). Returns (new_lat, new_lon).
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

- [ ] **Step 5: Refactor `position_fusion.py` to use `geo_utils.project_position`**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/position_fusion.py
"""GPS+IMU dead-reckoning position fusion with a growing error-circle
uncertainty radius. See design spec: Architecture -- Positioning.

Deliberately simple: forward-acceleration-only IMU model (not full 3-axis
inertial fusion), flat-earth degrees<->meters approximation (fine at the
scale of a single geofenced field). No wheel encoders -- velocity comes
from integrating accelerometer readings, which drifts, which is exactly
why the error circle exists and why it resets at every GPS fix.
"""
from __future__ import annotations

from dataclasses import dataclass

from papaya_mission.geo_utils import project_position


@dataclass
class GpsFix:
    lat: float
    lon: float
    accuracy_m: float
    timestamp: float


@dataclass
class ImuReading:
    heading_deg: float
    forward_acceleration_mps2: float
    timestamp: float


@dataclass
class PositionEstimate:
    lat: float
    lon: float
    error_radius_m: float
    timestamp: float


class PositionFusion:
    def __init__(self, initial_fix: GpsFix, drift_rate_m_per_s: float = 0.5):
        self._lat = initial_fix.lat
        self._lon = initial_fix.lon
        self._error_radius_m = initial_fix.accuracy_m
        self._velocity_mps = 0.0
        self._last_timestamp = initial_fix.timestamp
        self._drift_rate_m_per_s = drift_rate_m_per_s

    @property
    def current_estimate(self) -> PositionEstimate:
        return PositionEstimate(
            lat=self._lat,
            lon=self._lon,
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

        self._error_radius_m += self._drift_rate_m_per_s * dt
        self._last_timestamp = reading.timestamp

        return self.current_estimate
```

- [ ] **Step 6: Refactor `coverage_pattern.py` to use `geo_utils`'s constant**

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

- [ ] **Step 7: Refactor `exclusion_check.py` to use `geo_utils`'s constant**

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

- [ ] **Step 8: Run the full existing test suite and verify zero regressions**

Run: `pytest -v`
Expected: PASS — every test from the prior plan (`test_position_fusion.py`, `test_coverage_pattern.py`, `test_exclusion_check.py`, `test_integration.py`) still passes unchanged, plus the 5 new `test_geo_utils.py` tests. If anything in the prior suite fails, the refactor introduced a behavior change — stop and diagnose before continuing; do not edit the prior tests to make them pass.

- [ ] **Step 9: Commit**

```bash
git add pathfinder-autonomous/pi-mission
git commit -m "refactor(pi-mission): extract shared geo_utils from position/coverage/exclusion modules"
```

---

### Task 2: Obstacle domain model

**Files:**
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/obstacle.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_obstacle.py`

**Interfaces:**
- Produces: `papaya_mission.obstacle.Obstacle` — frozen dataclass with `position: tuple[float, float]` (lon, lat), `position_uncertainty_m: float`, `type: str`, `classification_confidence: float`, `detection_method: Literal["ultrasonic+camera", "contact-only"]`, `status: Literal["temporary", "permanent-pending"]`, `first_detected_at: float`, `last_confirmed_at: float | None = None`. Used by Tasks 4 and 5, and by the later Pi-telemetry-and-sync plan when persisting to the local store. Deliberately excludes lifecycle fields (`id`, `review_status`, `reviewed_by`, `reviewed_at`, `synced_at`) owned by that later plan.

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_obstacle.py
import dataclasses

import pytest

from papaya_mission.obstacle import Obstacle


def test_obstacle_is_constructible():
    obstacle = Obstacle(
        position=(-85.0005, 38.0005),
        position_uncertainty_m=2.0,
        type="barrel",
        classification_confidence=0.9,
        detection_method="ultrasonic+camera",
        status="permanent-pending",
        first_detected_at=10.0,
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
        first_detected_at=10.0,
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
"""
from __future__ import annotations

from dataclasses import dataclass
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
    first_detected_at: float
    last_confirmed_at: float | None = None
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
- Produces: `papaya_mission.classification.{LOW_CONFIDENCE_THRESHOLD, classify_permanence(classified_type: str, confidence: float) -> Literal["temporary", "permanent-pending"]}`. Used by Task 4's `obstacle_from_ultrasonic_camera_detection`.

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_classification.py
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
    if confidence < LOW_CONFIDENCE_THRESHOLD:
        return "temporary"
    if classified_type in _PERMANENT_TYPES:
        return "permanent-pending"
    return "temporary"
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_classification.py -v`
Expected: PASS (5 passed)

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
- Consumes: `papaya_mission.geo_utils.project_position` (Task 1), `papaya_mission.classification.classify_permanence` (Task 3), `papaya_mission.obstacle.Obstacle` (Task 2), `papaya_mission.position_fusion.PositionEstimate` (prior plan).
- Produces: `papaya_mission.obstacle_detection.{obstacle_from_ultrasonic_camera_detection(rover_position, bearing_deg, range_m, classified_type, classification_confidence, detected_at) -> Obstacle, obstacle_from_bump_contact(rover_position, detected_at) -> Obstacle}`. The mission-flow state machine plan calls these whenever a sensor reports a detection.

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_obstacle_detection.py
from papaya_mission.obstacle_detection import (
    obstacle_from_bump_contact,
    obstacle_from_ultrasonic_camera_detection,
)
from papaya_mission.position_fusion import PositionEstimate

ROVER_POSITION = PositionEstimate(lat=38.0, lon=-85.0, error_radius_m=1.5, timestamp=10.0)


def test_ultrasonic_camera_detection_projects_position_from_bearing_range():
    obstacle = obstacle_from_ultrasonic_camera_detection(
        rover_position=ROVER_POSITION,
        bearing_deg=0.0,  # north
        range_m=10.0,
        classified_type="barrel",
        classification_confidence=0.9,
        detected_at=11.0,
    )

    obstacle_lon, obstacle_lat = obstacle.position
    assert obstacle_lat > ROVER_POSITION.lat  # north of the rover
    assert obstacle.type == "barrel"
    assert obstacle.status == "permanent-pending"
    assert obstacle.detection_method == "ultrasonic+camera"
    assert obstacle.position_uncertainty_m == ROVER_POSITION.error_radius_m


def test_ultrasonic_camera_detection_low_confidence_stays_temporary():
    obstacle = obstacle_from_ultrasonic_camera_detection(
        rover_position=ROVER_POSITION,
        bearing_deg=0.0,
        range_m=10.0,
        classified_type="barrel",
        classification_confidence=0.1,
        detected_at=11.0,
    )

    assert obstacle.status == "temporary"


def test_bump_contact_is_always_permanent_pending_and_unknown_type():
    obstacle = obstacle_from_bump_contact(rover_position=ROVER_POSITION, detected_at=12.0)

    assert obstacle.type == "unknown"
    assert obstacle.status == "permanent-pending"
    assert obstacle.detection_method == "contact-only"
    assert obstacle.position == (ROVER_POSITION.lon, ROVER_POSITION.lat)
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

from papaya_mission.classification import classify_permanence
from papaya_mission.geo_utils import project_position
from papaya_mission.obstacle import Obstacle
from papaya_mission.position_fusion import PositionEstimate


def obstacle_from_ultrasonic_camera_detection(
    rover_position: PositionEstimate,
    bearing_deg: float,
    range_m: float,
    classified_type: str,
    classification_confidence: float,
    detected_at: float,
) -> Obstacle:
    """A proactively detected obstacle: ultrasonic gives bearing/range,
    the AI camera gives type + confidence. Position uncertainty is
    inherited from the rover's own current error-circle radius --
    sensor-specific range/bearing noise isn't modeled separately for v1.
    """
    obstacle_lat, obstacle_lon = project_position(
        rover_position.lat, rover_position.lon, bearing_deg, range_m
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
    detected_at: float,
) -> Obstacle:
    """A reactive detection: something was hit that proactive sensors
    missed. No type classification is possible, so it's always flagged
    for human review (permanent-pending) rather than silently logged as
    temporary -- a bump contact is real, actionable information about a
    sensing gap, unlike a low-confidence camera reading that's more
    likely just noise.
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
Expected: PASS (3 passed)

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
- Produces: `papaya_mission.resume_validation.{ReconciliationResult, reconcile_obstacles(known_obstacles: list[Obstacle], freshly_detected: list[Obstacle], now: float, match_radius_m: float = 3.0) -> ReconciliationResult}`. `ReconciliationResult` has `.confirmed` (known obstacles matched to a fresh detection, `last_confirmed_at` updated), `.cleared` (temporary, no match — caller removes these), `.discrepancies` (permanent-pending, no match — caller flags, never removes). The mission-flow state machine plan calls this during a resume pass (design spec: Mission Flow — Resume validation).

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_resume_validation.py
from papaya_mission.obstacle import Obstacle
from papaya_mission.resume_validation import reconcile_obstacles


def _obstacle(lon, lat, status, obstacle_type="barrel"):
    return Obstacle(
        position=(lon, lat),
        position_uncertainty_m=1.0,
        type=obstacle_type,
        classification_confidence=0.9,
        detection_method="ultrasonic+camera",
        status=status,
        first_detected_at=0.0,
    )


def test_matched_obstacle_is_confirmed_with_updated_timestamp():
    known = _obstacle(-85.0, 38.0, "temporary")
    fresh = _obstacle(-85.0, 38.0, "temporary")

    result = reconcile_obstacles([known], [fresh], now=100.0)

    assert len(result.confirmed) == 1
    assert result.confirmed[0].last_confirmed_at == 100.0
    assert result.confirmed[0].position == known.position
    assert result.cleared == []
    assert result.discrepancies == []


def test_missing_temporary_obstacle_is_cleared_not_flagged():
    known = _obstacle(-85.0, 38.0, "temporary")

    result = reconcile_obstacles([known], freshly_detected=[], now=100.0)

    assert result.cleared == [known]
    assert result.discrepancies == []
    assert result.confirmed == []


def test_missing_permanent_pending_obstacle_is_flagged_not_removed():
    known = _obstacle(-85.0, 38.0, "permanent-pending")

    result = reconcile_obstacles([known], freshly_detected=[], now=100.0)

    assert result.discrepancies == [known]
    assert result.cleared == []
    assert result.confirmed == []


def test_far_away_detection_does_not_count_as_a_match():
    known = _obstacle(-85.0, 38.0, "temporary")
    far_away = _obstacle(-84.0, 37.0, "temporary")  # well beyond match_radius_m

    result = reconcile_obstacles([known], [far_away], now=100.0, match_radius_m=3.0)

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
    now: float,
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
from papaya_mission.obstacle_detection import (
    obstacle_from_bump_contact,
    obstacle_from_ultrasonic_camera_detection,
)
from papaya_mission.position_fusion import PositionEstimate
from papaya_mission.resume_validation import reconcile_obstacles


def test_sweep_then_resume_pass_reconciles_correctly():
    rover_position = PositionEstimate(lat=38.0, lon=-85.0, error_radius_m=1.5, timestamp=0.0)

    barrel = obstacle_from_ultrasonic_camera_detection(
        rover_position,
        bearing_deg=0.0,
        range_m=5.0,
        classified_type="barrel",
        classification_confidence=0.9,
        detected_at=1.0,
    )
    chair = obstacle_from_ultrasonic_camera_detection(
        rover_position,
        bearing_deg=180.0,
        range_m=5.0,
        classified_type="chair",
        classification_confidence=0.9,
        detected_at=2.0,
    )
    known_obstacles = [barrel, chair]
    assert barrel.status == "permanent-pending"
    assert chair.status == "temporary"

    # Resume pass: the barrel is still there, the chair has been moved
    # (no longer detected), and a bump reveals something proactive
    # sensors missed entirely.
    fresh_barrel = obstacle_from_ultrasonic_camera_detection(
        rover_position,
        bearing_deg=0.0,
        range_m=5.0,
        classified_type="barrel",
        classification_confidence=0.9,
        detected_at=100.0,
    )
    bump_discovery = obstacle_from_bump_contact(rover_position, detected_at=101.0)

    result = reconcile_obstacles(known_obstacles, [fresh_barrel], now=100.0)

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
fusion with a growing error-circle, boustrophedon coverage-pattern
generation, exclusion-zone intrusion checks, and obstacle
detection/classification/resume-reconciliation. See
`docs/superpowers/specs/2026-09-24-mp1-map-detect-explore-design.md` for
the design this implements.

No hardware I/O here -- `GpsFix`/`ImuReading`/classification
results/bump events are all plain data a later sensor-driver layer will
produce from real hardware; this package only does the math and
decision logic. No persistence or orchestration either -- that's the
mission-flow state machine plan that imports these modules.

## Run the tests

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    pytest -v

## Modules

- `geo_utils.py` — shared degrees/meters helpers (`project_position`,
  `flat_earth_distance_m`) used by every other module.
- `position_fusion.py` — `PositionFusion`: seed with a `GpsFix`, feed
  `ImuReading`s between fixes, read `.current_estimate` for the fused
  position + error-circle radius.
- `coverage_pattern.py` — `generate_coverage_pattern(inclusive,
  exclusions, row_spacing_m)`: ordered `(lon, lat)` lawnmower waypoints.
- `exclusion_check.py` — `find_intruded_exclusion(position,
  exclusions)`: which exclusion zone (if any) a position is inside, and
  how deep.
- `obstacle.py` — `Obstacle`: the detection domain object.
- `classification.py` — `classify_permanence(type, confidence)`: the
  permanent/temporary heuristic, with a low-confidence safety override.
- `obstacle_detection.py` — turns a sensor detection (ultrasonic+camera,
  or a bump contact) into an `Obstacle` at an absolute position.
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

- **Spec coverage:** Detection (position + type + permanent/temporary tagging) ✓ Task 4. Bump contact (immediate, always flagged for review) ✓ Task 4. Low-confidence classification never promoted ✓ Task 3. Resume validation (confirm/clear/flag-discrepancy, never silently remove permanent-candidates) ✓ Task 5. The shared geometry refactor (Task 1) keeps the prior plan's modules DRY without changing their observable behavior — verified by running its full existing test suite unchanged. Real camera/ML model integration, real bump-sensor I2C bus reading, persistence, sync, and sweep-session orchestration are explicitly out of scope — later plans.
- **Placeholder scan:** no TBD/TODO; every step has runnable code.
- **Type consistency:** `Obstacle.position` is `(lon, lat)` everywhere it's produced (Task 4) and consumed (Task 5's `flat_earth_distance_m`), matching the GeoJSON coordinate-order convention from the backend plan. `PositionEstimate` fields (`lat`, `lon`, `error_radius_m`) are read the same way in Task 4 as they're defined in the prior plan — no renamed/mismatched fields.
