# MP-1 Position & Coverage Geometry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pure, hardware-free geometry/algorithm layer the Pi mission software runs on: GPS+IMU dead-reckoning position fusion with a growing error-circle, Shapely-based lawnmower coverage-pattern generation, and exclusion-zone intrusion depth checks.

**Architecture:** Three independent, side-effect-free modules under a `papaya_mission` package. No hardware I/O, no persistence, no network — GPS and IMU readings are plain dataclasses fed in by whatever calls this code (a later "sensor drivers" task wires up real hardware; a later "mission flow" plan wires up the orchestration state machine). Everything here is fully testable with synthetic inputs.

**Tech Stack:** Python 3.11 (matches Raspberry Pi OS Bookworm's default — this code is meant to run natively on the Pi, unlike the Docker-hosted backend, so it targets what's actually there without requiring a newer Python install), Shapely 2.x, pytest.

## Global Constraints

- New code lives under `pathfinder-autonomous/pi-mission/`, alongside `pathfinder-autonomous/backend/` from the prior plan.
- Position/polygon data crossing module boundaries uses the same GeoJSON convention as the backend: **coordinate order `[longitude, latitude]`**. Internally, Shapely geometry objects are used once GeoJSON has been converted via `shapely.geometry.shape()` — no custom GeoJSON Pydantic models are duplicated here (the backend's `GeoPoint`/`GeoPolygon` aren't imported; this is a separate deployable, and duplicating ~30 lines is cheaper than standing up a shared internal package for two consumers).
- All degrees↔meters conversions use one constant, `METERS_PER_DEGREE_LAT = 111_320.0`, applied consistently across modules — a flat-earth approximation that ignores longitude compression by latitude. Acceptable at the scale of a single geofenced field (design spec: Positioning — "MP-1's low travel speed" reasoning applies to this simplification too); revisit if a future mission operates over a much larger area.
- No wheel encoders, per the design spec — velocity for dead reckoning comes from integrating accelerometer readings (which drifts), not measured wheel speed. This is exactly why the error-circle radius exists and why it resets at every GPS fix. (Design spec: Architecture — Positioning.)
- This plan does not implement obstacle detection/classification or the mission-flow state machine (interrupt/resume/validation) — those are later plans that import from here.

---

## File Structure

```
pathfinder-autonomous/
  pi-mission/
    requirements.txt
    papaya_mission/
      __init__.py
      position_fusion.py      # GpsFix, ImuReading, PositionEstimate, PositionFusion
      coverage_pattern.py      # generate_coverage_pattern()
      exclusion_check.py        # exclusion_intrusion_depth_m(), find_intruded_exclusion()
    tests/
      __init__.py
      test_position_fusion.py
      test_coverage_pattern.py
      test_exclusion_check.py
      test_integration.py
```

---

### Task 1: Project scaffolding

**Files:**
- Create: `pathfinder-autonomous/pi-mission/requirements.txt`
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/__init__.py`
- Create: `pathfinder-autonomous/pi-mission/tests/__init__.py`

**Interfaces:**
- Produces: an importable `papaya_mission` package and a `tests/` directory that resolves it (via `pyproject.toml`'s implicit rootdir or a `conftest.py`-free `sys.path` setup — see Step 2).

- [ ] **Step 1: Create the directory and dependencies file**

`pathfinder-autonomous/pi-mission/requirements.txt`:

```
shapely==2.0.6
pytest==8.3.3
```

Create empty `pathfinder-autonomous/pi-mission/papaya_mission/__init__.py` and `pathfinder-autonomous/pi-mission/tests/__init__.py`.

- [ ] **Step 2: Create a venv, install dependencies, and add a pytest config so `papaya_mission` resolves**

```bash
cd pathfinder-autonomous/pi-mission
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

`pathfinder-autonomous/pi-mission/pytest.ini`:

```ini
[pytest]
pythonpath = .
```

This lets `tests/test_*.py` do `from papaya_mission.x import y` without installing the package.

- [ ] **Step 3: Verify the empty test suite runs**

Run: `pytest -v`
Expected: `no tests ran` (not an error) — confirms pytest picks up the directory correctly before any real code exists.

- [ ] **Step 4: Commit**

```bash
git add pathfinder-autonomous/pi-mission
git commit -m "chore(pi-mission): scaffold papaya_mission package"
```

---

### Task 2: Position fusion (GPS + IMU dead reckoning with error circle)

**Files:**
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/position_fusion.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_position_fusion.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `papaya_mission.position_fusion.{GpsFix, ImuReading, PositionEstimate, PositionFusion}`. `PositionFusion(initial_fix: GpsFix, drift_rate_m_per_s: float = 0.5)`; `.on_gps_fix(fix: GpsFix) -> PositionEstimate`; `.on_imu_reading(reading: ImuReading) -> PositionEstimate`; `.current_estimate -> PositionEstimate` (property). `PositionEstimate` has `.lat`, `.lon`, `.error_radius_m`, `.timestamp`. Later plans (mission flow state machine) call `on_gps_fix`/`on_imu_reading` as readings arrive and read `current_estimate` to drive navigation and exclusion-zone checks.

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_position_fusion.py
import math

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

    # heading 0 (north) with forward acceleration should move lat north (increase)
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
    assert corrected.error_radius_m == 1.5  # reset, not the grown drift value


def test_zero_or_negative_dt_is_ignored():
    fix = GpsFix(lat=38.0, lon=-85.0, accuracy_m=2.0, timestamp=5.0)
    fusion = PositionFusion(fix)

    estimate = fusion.on_imu_reading(
        ImuReading(heading_deg=0.0, forward_acceleration_mps2=5.0, timestamp=5.0)
    )

    assert estimate.lat == 38.0
    assert estimate.lon == -85.0
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_position_fusion.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'papaya_mission.position_fusion'`

- [ ] **Step 3: Write the implementation**

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

import math
from dataclasses import dataclass

METERS_PER_DEGREE_LAT = 111_320.0


@dataclass
class GpsFix:
    lat: float
    lon: float
    accuracy_m: float
    timestamp: float  # seconds; just needs consistent units with ImuReading


@dataclass
class ImuReading:
    heading_deg: float  # compass heading, 0 = north, clockwise positive
    forward_acceleration_mps2: float  # signed, positive = accelerating forward
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

        heading_rad = math.radians(reading.heading_deg)
        self._lat += (distance_m * math.cos(heading_rad)) / METERS_PER_DEGREE_LAT
        self._lon += (distance_m * math.sin(heading_rad)) / (
            METERS_PER_DEGREE_LAT * math.cos(math.radians(self._lat))
        )

        self._error_radius_m += self._drift_rate_m_per_s * dt
        self._last_timestamp = reading.timestamp

        return self.current_estimate
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_position_fusion.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/position_fusion.py pathfinder-autonomous/pi-mission/tests/test_position_fusion.py
git commit -m "feat(pi-mission): add GPS+IMU dead-reckoning position fusion"
```

---

### Task 3: Coverage pattern generation

**Files:**
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/coverage_pattern.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_coverage_pattern.py`

**Interfaces:**
- Consumes: `shapely.geometry.Polygon` (not this plan's own types — callers convert GeoJSON via `shapely.geometry.shape()` before calling in).
- Produces: `papaya_mission.coverage_pattern.generate_coverage_pattern(inclusive: Polygon, exclusions: list[Polygon], row_spacing_m: float) -> list[tuple[float, float]]`, returning an ordered boustrophedon (lawnmower) waypoint list as `(lon, lat)` tuples. Later plans wrap this into `{order, position}` waypoint records (design spec: Data Model — Sweep session `pattern`) and feed it into the mission-flow state machine.

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_coverage_pattern.py
from shapely.geometry import Polygon

from papaya_mission.coverage_pattern import generate_coverage_pattern

FIELD = Polygon(
    [
        (-85.001, 38.000),
        (-85.001, 38.001),
        (-85.000, 38.001),
        (-85.000, 38.000),
        (-85.001, 38.000),
    ]
)


def test_generates_multiple_rows_covering_the_field():
    waypoints = generate_coverage_pattern(FIELD, exclusions=[], row_spacing_m=20.0)

    assert len(waypoints) >= 4  # at least 2 rows x 2 endpoints each
    lats = [lat for _, lat in waypoints]
    assert min(lats) >= 38.000
    assert max(lats) <= 38.001


def test_rows_alternate_direction_boustrophedon():
    waypoints = generate_coverage_pattern(FIELD, exclusions=[], row_spacing_m=20.0)

    first_row = waypoints[0:2]
    assert first_row[0][0] < first_row[1][0]  # row 0: west to east

    second_row = waypoints[2:4]
    assert second_row[0][0] > second_row[1][0]  # row 1: east to west


def test_exclusion_zone_removes_covered_area():
    exclusion = Polygon(
        [
            (-85.0007, 38.0003),
            (-85.0007, 38.0007),
            (-85.0003, 38.0007),
            (-85.0003, 38.0003),
            (-85.0007, 38.0003),
        ]
    )

    waypoints = generate_coverage_pattern(FIELD, exclusions=[exclusion], row_spacing_m=20.0)

    for lon, lat in waypoints:
        assert not (-85.0007 < lon < -85.0003 and 38.0003 < lat < 38.0007)


def test_exclusion_covering_entire_field_yields_no_waypoints():
    full_cover = Polygon(
        [
            (-85.002, 37.999),
            (-85.002, 38.002),
            (-84.999, 38.002),
            (-84.999, 37.999),
            (-85.002, 37.999),
        ]
    )

    waypoints = generate_coverage_pattern(FIELD, exclusions=[full_cover], row_spacing_m=20.0)

    assert waypoints == []
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_coverage_pattern.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'papaya_mission.coverage_pattern'`

- [ ] **Step 3: Write the implementation**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/coverage_pattern.py
"""Boustrophedon (lawnmower) coverage-pattern generation over a geofence,
avoiding exclusion zones. Deliberately simple per the design spec's Route
Planning notes -- open fields, gentle slopes, no road-network routing.
"""
from __future__ import annotations

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

METERS_PER_DEGREE_LAT = 111_320.0


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
    lat = miny + row_spacing_deg / 2  # start half a row in from the edge

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

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_coverage_pattern.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/coverage_pattern.py pathfinder-autonomous/pi-mission/tests/test_coverage_pattern.py
git commit -m "feat(pi-mission): add boustrophedon coverage pattern generator"
```

---

### Task 4: Exclusion-zone intrusion check

**Files:**
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/exclusion_check.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_exclusion_check.py`

**Interfaces:**
- Consumes: `shapely.geometry.Polygon` (same convention as Task 3).
- Produces: `papaya_mission.exclusion_check.exclusion_intrusion_depth_m(position: tuple[float, float], exclusion: Polygon) -> float | None` and `find_intruded_exclusion(position: tuple[float, float], exclusions: list[Polygon]) -> tuple[Polygon, float] | None`. The mission-flow state machine plan calls `find_intruded_exclusion` on the current position estimate (from Task 2) and compares the returned depth against a rover-length threshold to decide auto-reverse vs. wait-for-help (design spec: Mission Flow — Exclusion-zone intrusion).

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_exclusion_check.py
from shapely.geometry import Polygon

from papaya_mission.exclusion_check import (
    exclusion_intrusion_depth_m,
    find_intruded_exclusion,
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


def test_position_outside_returns_none():
    assert exclusion_intrusion_depth_m((-85.02, 38.02), POND) is None


def test_position_inside_returns_positive_depth_in_meters():
    depth = exclusion_intrusion_depth_m((-85.0005, 38.0005), POND)

    assert depth is not None
    assert depth > 0.0


def test_deeper_intrusion_has_larger_depth():
    center_depth = exclusion_intrusion_depth_m((-85.0005, 38.0005), POND)
    near_edge_depth = exclusion_intrusion_depth_m((-85.00069, 38.0003001), POND)

    assert center_depth > near_edge_depth


def test_find_intruded_exclusion_returns_first_match():
    other = Polygon(
        [(-84.0, 37.0), (-84.0, 37.1), (-83.9, 37.1), (-83.9, 37.0), (-84.0, 37.0)]
    )

    result = find_intruded_exclusion((-85.0005, 38.0005), [other, POND])

    assert result is not None
    matched_polygon, depth = result
    assert matched_polygon == POND
    assert depth > 0.0


def test_find_intruded_exclusion_returns_none_outside_all():
    other = Polygon(
        [(-84.0, 37.0), (-84.0, 37.1), (-83.9, 37.1), (-83.9, 37.0), (-84.0, 37.0)]
    )

    result = find_intruded_exclusion((-85.02, 38.02), [other, POND])

    assert result is None
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_exclusion_check.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'papaya_mission.exclusion_check'`

- [ ] **Step 3: Write the implementation**

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

METERS_PER_DEGREE_LAT = 111_320.0


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

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_exclusion_check.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/exclusion_check.py pathfinder-autonomous/pi-mission/tests/test_exclusion_check.py
git commit -m "feat(pi-mission): add exclusion-zone intrusion depth check"
```

---

### Task 5: Integration test and dev documentation

**Files:**
- Create: `pathfinder-autonomous/pi-mission/tests/test_integration.py`
- Create: `pathfinder-autonomous/pi-mission/README.md`

**Interfaces:**
- Consumes: everything from Tasks 2–4.
- Produces: nothing new — proves the three modules compose into the shape the mission-flow plan will actually use them in, and documents the package for whoever picks up that plan next.

- [ ] **Step 1: Write the integration test**

Simulates the real usage pattern: generate a coverage pattern, walk a simulated rover along it with dead-reckoned position updates, and check exclusion status along the way.

```python
# pathfinder-autonomous/pi-mission/tests/test_integration.py
from shapely.geometry import Polygon

from papaya_mission.coverage_pattern import generate_coverage_pattern
from papaya_mission.exclusion_check import find_intruded_exclusion
from papaya_mission.position_fusion import GpsFix, ImuReading, PositionFusion

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


def test_generated_pattern_waypoints_are_never_inside_the_pond():
    waypoints = generate_coverage_pattern(FIELD, exclusions=[POND], row_spacing_m=15.0)

    for lon, lat in waypoints:
        assert find_intruded_exclusion((lon, lat), [POND]) is None


def test_dead_reckoned_position_along_first_leg_stays_reasonable():
    waypoints = generate_coverage_pattern(FIELD, exclusions=[], row_spacing_m=20.0)
    start_lon, start_lat = waypoints[0]

    fusion = PositionFusion(
        GpsFix(lat=start_lat, lon=start_lon, accuracy_m=2.0, timestamp=0.0)
    )

    # Simulate driving toward the second waypoint for 5 one-second IMU ticks.
    for t in range(1, 6):
        fusion.on_imu_reading(
            ImuReading(heading_deg=90.0, forward_acceleration_mps2=0.3, timestamp=float(t))
        )

    estimate = fusion.current_estimate
    # Moved east (increasing longitude) from the start point, error grew.
    assert estimate.lon > start_lon
    assert estimate.error_radius_m > 2.0
```

- [ ] **Step 2: Run it and verify it passes**

Run: `pytest tests/test_integration.py -v`
Expected: PASS — if the second test fails, double check the heading convention (0=north, 90=east per `ImuReading.heading_deg`'s docstring in `position_fusion.py`).

- [ ] **Step 3: Write the dev README**

```markdown
# Papaya Pathfinder — Pi Mission (Position & Coverage Geometry)

Pure geometry/algorithm layer for MP-1: GPS+IMU dead-reckoning position
fusion with a growing error-circle, boustrophedon coverage-pattern
generation, and exclusion-zone intrusion checks. See
`docs/superpowers/specs/2026-09-24-mp1-map-detect-explore-design.md` for
the design this implements.

No hardware I/O here -- `GpsFix`/`ImuReading` are plain data a later
sensor-driver layer will produce from real hardware; this package only
does the math. No persistence or orchestration either -- that's the
mission-flow state machine plan that imports these modules.

## Run the tests

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    pytest -v

## Modules

- `position_fusion.py` — `PositionFusion`: seed with a `GpsFix`, feed
  `ImuReading`s between fixes, read `.current_estimate` for the fused
  position + error-circle radius.
- `coverage_pattern.py` — `generate_coverage_pattern(inclusive, exclusions,
  row_spacing_m)`: ordered `(lon, lat)` lawnmower waypoints.
- `exclusion_check.py` — `find_intruded_exclusion(position, exclusions)`:
  which exclusion zone (if any) a position is inside, and how deep.
```

- [ ] **Step 4: Commit**

```bash
git add pathfinder-autonomous/pi-mission
git commit -m "test(pi-mission): add integration test and README"
```

---

## Self-Review Notes

- **Spec coverage:** GPS+IMU dead reckoning with error-circle (Architecture — Positioning) ✓ Task 2. Coverage-pattern auto-generation avoiding exclusion zones (Mission Flow — Pre-mission setup) ✓ Task 3. Exclusion-zone intrusion depth, feeding the one-rover-length auto-reverse-vs-wait-for-help rule (Mission Flow — Exclusion-zone intrusion) ✓ Task 4 (decision logic itself is explicitly left to the mission-flow plan). Obstacle detection/classification, the sweep-session state machine, resume/validation, and any real sensor hardware integration are explicitly out of scope — later plans.
- **Placeholder scan:** no TBD/TODO; every step has runnable code.
- **Type consistency:** `PositionEstimate.lat/lon` (`float`) match `GpsFix.lat/lon`. `generate_coverage_pattern` and `find_intruded_exclusion` both consume plain Shapely `Polygon` objects and `(lon, lat)` tuples consistently — no module invents its own coordinate representation.
