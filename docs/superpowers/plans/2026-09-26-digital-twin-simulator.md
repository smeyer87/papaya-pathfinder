# Digital-Twin Simulator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a coherent simulated sensor world (`TwinWorld`) for the Pi-mission package — one shared rover/obstacle/mast state that GPS, IMU, ultrasonic, camera, and bump-event readings are all derived from, so scenario tests can rely on them agreeing with each other, unlike today's `SimulatedSensorHub`/`FakeEsp32Link`, where each field is scripted independently.

**Architecture:** A single `TwinWorld` object (new module `digital_twin.py`) owns all shared state — true rover position/heading/speed, a mast that sweeps back and forth like a bounded radar, static obstacles, exclusion zones, and a seeded RNG for GPS jitter. Thin private adapter classes implement one `SensorHub`/`Esp32Link` Protocol method each by reading through to that shared state, exposed as `world.sensor_hub`/`world.esp32_link` — the same shape `SimulatedSensorHub`/`FakeEsp32Link` already present to `MissionRuntime`, so nothing downstream changes, only what's behind the Protocol.

**Tech Stack:** Python 3.12, Shapely 2.x, pytest — no new dependencies. Reuses `geo_utils.project_position`/`flat_earth_distance_m` for all position math; no new coordinate system.

## Global Constraints

- Additive only: `sensor_hub.py`'s `SimulatedSensorHub` and `esp32_link.py`'s `FakeEsp32Link` are untouched. This plan adds one new module used by new scenario tests.
- Movement is scenario-scripted, not autonomous: `world.step(dt_s, heading_deg, speed_mps)` sets the commanded heading/speed for that tick. No Pi→ESP32 drive-command interface exists yet to hook into instead — that is the ESP32 firmware plan's job, out of scope here.
- Coordinate frame is `(lat, lon)` throughout, reusing `geo_utils.project_position`/`flat_earth_distance_m` — no new coordinate math, no local-meters frame.
- GPS is the only noisy reading: true position is always known exactly inside `TwinWorld`; the reported `GpsFix` wanders within a disk of radius `gps_accuracy_m` around true position, sampled from a seeded RNG so tests stay reproducible. `world.gps_available = False` makes the GPS source return `None` (the GPS-loss scenario `MissionRuntime` already handles), instead of extreme noise.
- The ultrasonic+camera mast sweeps autonomously (no Pi command exists for it either) between `±mast_sweep_limit_deg` at `mast_turn_rate_dps`, with a beam half-angle of `mast_beam_half_angle_deg` around wherever it currently points. All three, plus `max_ultrasonic_range_m`, `gps_accuracy_m`, and `max_speed_mps`, are `TwinWorld` constructor parameters with defaults — never hardcoded module constants — since real sensor/processing-cycle numbers aren't chosen yet. Defaults: `mast_sweep_limit_deg=60.0`, `mast_turn_rate_dps=30.0` (deliberately conservative — real image-capture/classification and ultrasonic cycle times aren't scoped yet), `mast_beam_half_angle_deg=7.5`, `max_ultrasonic_range_m=5.0`, `gps_accuracy_m=3.0`, `max_speed_mps=2.0`.
- An ultrasonic/camera reading only fires when an obstacle is within the mast's *current* beam window (not the rover's heading) and within range. On a hit, the reported bearing is the mast's own current pointing angle, not the true bearing to the obstacle — a narrow-beam sensor cannot resolve position within its beam any finer than "something is in the direction I'm aimed."
- Bump contact is edge-triggered: a `BumpEvent` fires only on the tick true position newly enters an obstacle's `collision_radius_m` (not every tick while still touching), and further simulated movement stops (`step()` becomes a no-op for position) until `world.clear_halt()` is called — mirroring the ESP32's real autonomous bump-safety ownership (a hardware interrupt cuts the drive train independently of the Pi).
- Obstacles are static only (position, `collision_radius_m`, `classified_type`, `classification_confidence`); no moving obstacles, no IMU or non-GPS sensor noise — nothing in Mission Flow's decision logic needs them yet.
- Design spec: `docs/superpowers/specs/2026-09-26-digital-twin-simulator-design.md`.

---

## File Structure

```
pathfinder-autonomous/pi-mission/
  papaya_mission/
    digital_twin.py                 # NEW -- TwinWorld, TwinObstacle, private _Twin*
                                     #        adapters. Exposes world.sensor_hub /
                                     #        world.esp32_link.
  tests/
    test_digital_twin.py            # NEW -- the twin in isolation: kinematics, mast
                                     #        sweep, bump/halt, detection geometry,
                                     #        GPS jitter, adapter wiring
    test_digital_twin_scenarios.py  # NEW -- end-to-end scenarios driving a real
                                     #        MissionRuntime against the twin
```

Everything else (`sensor_hub.py`, `esp32_link.py`, `geo_utils.py`, `runtime.py`, `obstacle_detection.py`, `classification.py`, `local_store.py`, ...) is consumed as-is — this plan only adds `digital_twin.py` and its tests.

---

### Task 1: World core — rover kinematics, mast sweep, bump/collision, halt

**Files:**
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/digital_twin.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_digital_twin.py`

**Interfaces:**
- Consumes: `papaya_mission.geo_utils.{project_position, flat_earth_distance_m}`, `papaya_mission.esp32_link.BumpEvent`.
- Produces: `TwinObstacle(lat: float, lon: float, collision_radius_m: float, classified_type: str, classification_confidence: float)` (frozen, kw_only). `TwinWorld(start_lat: float, start_lon: float, *, gps_accuracy_m: float = 3.0, mast_sweep_limit_deg: float = 60.0, mast_turn_rate_dps: float = 30.0, mast_beam_half_angle_deg: float = 7.5, max_ultrasonic_range_m: float = 5.0, max_speed_mps: float = 2.0, start_time: datetime | None = None, rng_seed: int = 0)` with public attributes `lat`, `lon`, `heading_deg`, `speed_mps`, `clock_s`, `gps_accuracy_m`, `gps_available: bool`, `mast_angle_deg`, `mast_sweep_limit_deg`, `mast_turn_rate_dps`, `mast_beam_half_angle_deg`, `max_ultrasonic_range_m`, `max_speed_mps`, `obstacles: list[TwinObstacle]`, `exclusion_zones: list[Polygon]`, `geofence_updates_sent: list[list[str]]`, `ota_triggers: list[str]`; methods `step(dt_s, heading_deg, speed_mps) -> None`, `point_mast_at(relative_deg: float) -> None`, `clear_halt() -> None`. Later tasks read/write private `world._acceleration_mps2`, `world._halted_on_contact`, `world._pending_bump_events`, `world._rng`, and call private `world._advance_mast`/`world._check_bump_contacts` only from within `step()`.

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_digital_twin.py
import math

from papaya_mission.digital_twin import TwinObstacle, TwinWorld
from papaya_mission.geo_utils import flat_earth_distance_m, project_position


def test_step_moves_rover_along_heading_by_project_position():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0)

    world.step(dt_s=2.0, heading_deg=90.0, speed_mps=1.5)

    expected_lat, expected_lon = project_position(38.0, -85.0, bearing_deg=90.0, distance_m=3.0)
    assert math.isclose(world.lat, expected_lat, abs_tol=1e-9)
    assert math.isclose(world.lon, expected_lon, abs_tol=1e-9)
    assert world.heading_deg == 90.0
    assert world.speed_mps == 1.5


def test_step_advances_clock_and_derives_acceleration():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0)

    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=2.0)

    assert world.clock_s == 1.0
    assert world._acceleration_mps2 == 2.0  # 0 -> 2.0 m/s over 1s

    world.step(dt_s=0.5, heading_deg=0.0, speed_mps=1.0)

    assert world.clock_s == 1.5
    assert world._acceleration_mps2 == -2.0  # 2.0 -> 1.0 m/s over 0.5s


def test_mast_sweeps_and_reverses_exactly_at_limits():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0, mast_sweep_limit_deg=10.0, mast_turn_rate_dps=10.0)

    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=0.0)  # 0 -> 10 (hits the limit)
    assert world.mast_angle_deg == 10.0

    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=0.0)  # reverses: 10 -> 0
    assert world.mast_angle_deg == 0.0

    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=0.0)  # keeps going: 0 -> -10
    assert world.mast_angle_deg == -10.0


def test_point_mast_at_sets_angle_and_clamps_to_sweep_limit():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0, mast_sweep_limit_deg=45.0)

    world.point_mast_at(20.0)
    assert world.mast_angle_deg == 20.0

    world.point_mast_at(90.0)
    assert world.mast_angle_deg == 45.0


def test_bump_contact_fires_once_on_entry_not_every_tick():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0)
    obstacle_lat, obstacle_lon = project_position(38.0, -85.0, bearing_deg=0.0, distance_m=1.0)
    world.obstacles.append(TwinObstacle(
        lat=obstacle_lat, lon=obstacle_lon, collision_radius_m=0.5,
        classified_type="unknown", classification_confidence=0.0,
    ))

    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=1.0)  # arrives exactly at the obstacle
    assert world._halted_on_contact is True
    assert len(world._pending_bump_events) == 1

    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=1.0)  # still touching -- no second event
    assert len(world._pending_bump_events) == 1


def test_halted_rover_does_not_move_until_cleared():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0)
    obstacle_lat, obstacle_lon = project_position(38.0, -85.0, bearing_deg=0.0, distance_m=1.0)
    world.obstacles.append(TwinObstacle(
        lat=obstacle_lat, lon=obstacle_lon, collision_radius_m=0.5,
        classified_type="unknown", classification_confidence=0.0,
    ))
    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=1.0)
    position_at_halt = (world.lat, world.lon)

    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=1.0)
    assert (world.lat, world.lon) == position_at_halt
    assert world.speed_mps == 0.0

    world.clear_halt()
    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=1.0)
    assert (world.lat, world.lon) != position_at_halt


def test_moving_away_and_back_retriggers_bump_contact():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0)
    obstacle_lat, obstacle_lon = project_position(38.0, -85.0, bearing_deg=0.0, distance_m=1.0)
    world.obstacles.append(TwinObstacle(
        lat=obstacle_lat, lon=obstacle_lon, collision_radius_m=0.5,
        classified_type="unknown", classification_confidence=0.0,
    ))
    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=1.0)  # contact #1
    assert len(world._pending_bump_events) == 1
    world.clear_halt()

    world.step(dt_s=1.0, heading_deg=180.0, speed_mps=2.0)  # back away, clear of the collision radius
    distance_away = flat_earth_distance_m((world.lon, world.lat), (obstacle_lon, obstacle_lat))
    assert distance_away > 0.5

    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=2.0)  # drive back in -- contact #2
    assert len(world._pending_bump_events) == 2
```

- [ ] **Step 2: Run the tests and verify they fail**

Run (from `pathfinder-autonomous/pi-mission/`): `pytest tests/test_digital_twin.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'papaya_mission.digital_twin'`

- [ ] **Step 3: Write the implementation**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/digital_twin.py
"""Digital-twin simulator: one coherent virtual world that GPS, IMU,
ultrasonic, camera, and bump-event readings are all derived from, so a
scenario test can rely on them agreeing with each other -- unlike
SimulatedSensorHub/FakeEsp32Link, where each field is scripted
independently. See design spec:
docs/superpowers/specs/2026-09-26-digital-twin-simulator-design.md.

Movement is scenario-scripted (world.step(dt_s, heading_deg, speed_mps)),
not autonomous -- nothing in the codebase commands rover movement yet
(Phase 1 hardware is RC/ELRS-driven; the Pi->ESP32 autonomous drive-command
channel is the ESP32 firmware plan's job to define). The ultrasonic+camera
mast, like the ESP32's bump-safety interrupt, has no Pi command either, so
it sweeps autonomously every step() call.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from shapely.geometry import Polygon

from papaya_mission.esp32_link import BumpEvent
from papaya_mission.geo_utils import flat_earth_distance_m, project_position


@dataclass(frozen=True, kw_only=True)
class TwinObstacle:
    lat: float
    lon: float
    collision_radius_m: float
    classified_type: str
    classification_confidence: float


class TwinWorld:
    def __init__(
        self,
        start_lat: float,
        start_lon: float,
        *,
        gps_accuracy_m: float = 3.0,
        mast_sweep_limit_deg: float = 60.0,
        mast_turn_rate_dps: float = 30.0,
        mast_beam_half_angle_deg: float = 7.5,
        max_ultrasonic_range_m: float = 5.0,
        max_speed_mps: float = 2.0,
        start_time: datetime | None = None,
        rng_seed: int = 0,
    ) -> None:
        self.lat = start_lat
        self.lon = start_lon
        self.heading_deg = 0.0
        self.speed_mps = 0.0
        self.clock_s = 0.0
        self._start_time = start_time or datetime(2026, 1, 1, tzinfo=timezone.utc)
        self._acceleration_mps2 = 0.0

        self.gps_accuracy_m = gps_accuracy_m
        self.gps_available = True
        self._rng = random.Random(rng_seed)

        self.mast_sweep_limit_deg = mast_sweep_limit_deg
        # Real image-capture/classification latency and real ultrasonic
        # ranging cycle time aren't scoped yet -- either could mean the mast
        # physically moves on to a new angle before a reading actually
        # finishes, which this simulator does not model. Cheap to add once
        # real hardware/pipeline numbers exist, since this is a constructor
        # parameter rather than a hardcoded constant.
        self.mast_turn_rate_dps = mast_turn_rate_dps
        self.mast_beam_half_angle_deg = mast_beam_half_angle_deg
        self.mast_angle_deg = 0.0
        self._mast_direction = 1.0

        self.max_ultrasonic_range_m = max_ultrasonic_range_m
        self.max_speed_mps = max_speed_mps

        self.obstacles: list[TwinObstacle] = []
        self.exclusion_zones: list[Polygon] = []

        self._halted_on_contact = False
        self._contacted_obstacle_ids: set[int] = set()
        self._pending_bump_events: list[BumpEvent] = []
        self.geofence_updates_sent: list[list[str]] = []
        self.ota_triggers: list[str] = []

    def step(self, dt_s: float, heading_deg: float, speed_mps: float) -> None:
        self.clock_s += dt_s
        previous_speed = self.speed_mps

        if self._halted_on_contact:
            # The ESP32 has already cut the drive train via its own
            # hardware interrupt (see module docstring) -- the twin mirrors
            # that by refusing to advance position until clear_halt().
            self.speed_mps = 0.0
        else:
            self.heading_deg = heading_deg % 360.0
            self.speed_mps = speed_mps
            distance_m = speed_mps * dt_s
            self.lat, self.lon = project_position(self.lat, self.lon, self.heading_deg, distance_m)

        self._acceleration_mps2 = (self.speed_mps - previous_speed) / dt_s if dt_s > 0 else 0.0

        self._advance_mast(dt_s)
        self._check_bump_contacts()

    def point_mast_at(self, relative_deg: float) -> None:
        self.mast_angle_deg = max(-self.mast_sweep_limit_deg, min(self.mast_sweep_limit_deg, relative_deg))

    def clear_halt(self) -> None:
        self._halted_on_contact = False

    def _advance_mast(self, dt_s: float) -> None:
        self.mast_angle_deg += self._mast_direction * self.mast_turn_rate_dps * dt_s
        if self.mast_angle_deg >= self.mast_sweep_limit_deg:
            self.mast_angle_deg = self.mast_sweep_limit_deg
            self._mast_direction = -1.0
        elif self.mast_angle_deg <= -self.mast_sweep_limit_deg:
            self.mast_angle_deg = -self.mast_sweep_limit_deg
            self._mast_direction = 1.0

    def _check_bump_contacts(self) -> None:
        # Endpoint-only collision check: a fast enough step could in theory
        # "tunnel" past an obstacle within one step without ever landing
        # inside its collision_radius_m. Not modeled -- MP1_EXPECTED speeds
        # are low enough, relative to step size, that this hasn't mattered.
        now = self._start_time + timedelta(seconds=self.clock_s)
        still_touching: set[int] = set()
        for obstacle in self.obstacles:
            distance_m = flat_earth_distance_m((self.lon, self.lat), (obstacle.lon, obstacle.lat))
            if distance_m <= obstacle.collision_radius_m:
                still_touching.add(id(obstacle))
                if id(obstacle) not in self._contacted_obstacle_ids:
                    self._pending_bump_events.append(BumpEvent(detected_at=now))
                    self._halted_on_contact = True
        self._contacted_obstacle_ids = still_touching
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_digital_twin.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/digital_twin.py pathfinder-autonomous/pi-mission/tests/test_digital_twin.py
git commit -m "feat(pi-mission): add digital-twin world core (kinematics, mast sweep, bump/halt)"
```

---

### Task 2: Detection geometry — bearing/range, obstacle-in-view, drive_route

**Files:**
- Modify: `pathfinder-autonomous/pi-mission/papaya_mission/digital_twin.py`
- Modify: `pathfinder-autonomous/pi-mission/tests/test_digital_twin.py`

**Interfaces:**
- Consumes: `TwinWorld`, `TwinObstacle` from Task 1.
- Produces: private `TwinWorld._bearing_and_range_to(target_lat: float, target_lon: float) -> tuple[float, float]` (returns `(relative_bearing_deg, range_m)`, bearing relative to the rover's current heading, normalized to `(-180, 180]`), private `TwinWorld._obstacle_in_view() -> TwinObstacle | None` (nearest obstacle within the mast's current beam and `max_ultrasonic_range_m`, or `None`). Public `TwinWorld.drive_route(waypoints: list[tuple[float, float]], speed_mps: float, dt_s: float) -> None` (each waypoint is a `(lat, lon)` pair). Task 3's ultrasonic/camera adapters call `_obstacle_in_view`/`_bearing_and_range_to` directly.

- [ ] **Step 1: Write the failing tests**

Append to `test_digital_twin.py`:

```python
def test_bearing_and_range_to_matches_project_position_inverse():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0)
    target_lat, target_lon = project_position(38.0, -85.0, bearing_deg=30.0, distance_m=50.0)

    relative_bearing_deg, range_m = world._bearing_and_range_to(target_lat, target_lon)

    assert math.isclose(relative_bearing_deg, 30.0, abs_tol=1e-6)  # heading_deg is 0.0 by default
    assert math.isclose(range_m, 50.0, rel_tol=1e-6)


def test_bearing_and_range_to_is_relative_to_current_heading():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0)
    world.heading_deg = 30.0
    target_lat, target_lon = project_position(38.0, -85.0, bearing_deg=30.0, distance_m=50.0)

    relative_bearing_deg, range_m = world._bearing_and_range_to(target_lat, target_lon)

    assert math.isclose(relative_bearing_deg, 0.0, abs_tol=1e-6)  # dead ahead once heading matches


def test_obstacle_in_view_requires_beam_and_range():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0, mast_beam_half_angle_deg=5.0, max_ultrasonic_range_m=10.0)
    near_ahead_lat, near_ahead_lon = project_position(38.0, -85.0, bearing_deg=0.0, distance_m=3.0)
    obstacle = TwinObstacle(
        lat=near_ahead_lat, lon=near_ahead_lon, collision_radius_m=0.3,
        classified_type="barrel", classification_confidence=0.9,
    )
    world.obstacles.append(obstacle)

    world.point_mast_at(0.0)
    assert world._obstacle_in_view() is obstacle

    world.point_mast_at(20.0)  # outside the 5-degree beam
    assert world._obstacle_in_view() is None


def test_obstacle_in_view_respects_max_range():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0, max_ultrasonic_range_m=2.0)
    far_ahead_lat, far_ahead_lon = project_position(38.0, -85.0, bearing_deg=0.0, distance_m=10.0)
    world.obstacles.append(TwinObstacle(
        lat=far_ahead_lat, lon=far_ahead_lon, collision_radius_m=0.3,
        classified_type="barrel", classification_confidence=0.9,
    ))

    world.point_mast_at(0.0)
    assert world._obstacle_in_view() is None


def test_obstacle_in_view_picks_the_nearest_of_several():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0)
    near_lat, near_lon = project_position(38.0, -85.0, bearing_deg=0.0, distance_m=2.0)
    far_lat, far_lon = project_position(38.0, -85.0, bearing_deg=0.0, distance_m=4.0)
    near = TwinObstacle(lat=near_lat, lon=near_lon, collision_radius_m=0.3, classified_type="post", classification_confidence=0.9)
    far = TwinObstacle(lat=far_lat, lon=far_lon, collision_radius_m=0.3, classified_type="barrel", classification_confidence=0.9)
    world.obstacles.extend([far, near])

    world.point_mast_at(0.0)
    assert world._obstacle_in_view() is near


def test_drive_route_arrives_near_each_waypoint_in_order():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0)
    waypoint_a = project_position(38.0, -85.0, bearing_deg=0.0, distance_m=10.0)
    waypoint_b = project_position(*waypoint_a, bearing_deg=90.0, distance_m=10.0)

    world.drive_route([waypoint_a, waypoint_b], speed_mps=2.0, dt_s=1.0)

    assert flat_earth_distance_m((world.lon, world.lat), (waypoint_b[1], waypoint_b[0])) < 2.0
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_digital_twin.py -v`
Expected: FAIL — `AttributeError: 'TwinWorld' object has no attribute '_bearing_and_range_to'` (and similar for `_obstacle_in_view`/`drive_route`)

- [ ] **Step 3: Write the implementation**

Add to `digital_twin.py`. First, add `math` to the imports (`import math` alongside `import random`). Then add these methods to `TwinWorld` (after `_check_bump_contacts`):

```python
    def _bearing_and_range_to(self, target_lat: float, target_lon: float) -> tuple[float, float]:
        """Inverts geo_utils.project_position: given a point this world
        already knows the absolute position of (an obstacle, a waypoint),
        returns the bearing relative to the rover's current heading and the
        range in meters. Nothing in production code needs this direction --
        obstacle_detection.py only ever goes bearing+range -> position,
        since a real rover never has ground truth for an object's position
        before detecting it. The twin has ground truth, so it needs the
        reverse to decide what a sensor would currently see.
        """
        lat_rad = math.radians(self.lat)
        dlat_m = (target_lat - self.lat) * geo_utils.METERS_PER_DEGREE_LAT
        dlon_m = (target_lon - self.lon) * geo_utils.METERS_PER_DEGREE_LAT * math.cos(lat_rad)
        absolute_bearing_deg = math.degrees(math.atan2(dlon_m, dlat_m)) % 360.0
        relative_bearing_deg = (absolute_bearing_deg - self.heading_deg + 180.0) % 360.0 - 180.0
        range_m = flat_earth_distance_m((self.lon, self.lat), (target_lon, target_lat))
        return relative_bearing_deg, range_m

    def _obstacle_in_view(self) -> TwinObstacle | None:
        best: tuple[float, TwinObstacle] | None = None
        for obstacle in self.obstacles:
            relative_bearing_deg, range_m = self._bearing_and_range_to(obstacle.lat, obstacle.lon)
            if range_m > self.max_ultrasonic_range_m:
                continue
            angle_off_mast = (relative_bearing_deg - self.mast_angle_deg + 180.0) % 360.0 - 180.0
            if abs(angle_off_mast) > self.mast_beam_half_angle_deg:
                continue
            if best is None or range_m < best[0]:
                best = (range_m, obstacle)
        return best[1] if best is not None else None

    def drive_route(self, waypoints: list[tuple[float, float]], speed_mps: float, dt_s: float) -> None:
        """Repeatedly steps toward each (lat, lon) waypoint in order at
        speed_mps, turning to face each new target exactly at its start --
        a convenience for scenarios that would rather not hand-compute
        per-leg headings themselves. Not a real path planner: distance
        remaining is decremented by a fixed step size rather than
        recomputed from position each step, so it can overshoot a waypoint
        by up to one step's travel distance before moving on to the next.
        """
        for target_lat, target_lon in waypoints:
            remaining_m = flat_earth_distance_m((self.lon, self.lat), (target_lon, target_lat))
            step_distance_m = speed_mps * dt_s
            while remaining_m > 0:
                bearing_deg, _ = self._bearing_and_range_to(target_lat, target_lon)
                self.step(dt_s, heading_deg=bearing_deg, speed_mps=speed_mps)
                remaining_m -= step_distance_m
```

Also add a new import line, `from papaya_mission import geo_utils`, right above the existing `from papaya_mission.geo_utils import flat_earth_distance_m, project_position` line (keep both lines) so `geo_utils.METERS_PER_DEGREE_LAT` is reachable in `_bearing_and_range_to`.

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_digital_twin.py -v`
Expected: PASS (13 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/digital_twin.py pathfinder-autonomous/pi-mission/tests/test_digital_twin.py
git commit -m "feat(pi-mission): add twin detection geometry and drive_route helper"
```

---

### Task 3: SensorHub adapters (GPS jitter, IMU, ultrasonic, camera)

**Files:**
- Modify: `pathfinder-autonomous/pi-mission/papaya_mission/digital_twin.py`
- Modify: `pathfinder-autonomous/pi-mission/tests/test_digital_twin.py`

**Interfaces:**
- Consumes: `TwinWorld._obstacle_in_view`, `TwinWorld._bearing_and_range_to`, `TwinWorld._rng`, `TwinWorld._acceleration_mps2` from Tasks 1-2; `papaya_mission.position_fusion.{GpsFix, ImuReading}`; `papaya_mission.sensor_hub.ObstacleDetection`.
- Produces: `TwinWorld.sensor_hub` attribute (added as the last line of `TwinWorld.__init__`), an object with `.gps.read() -> GpsFix | None`, `.imu.read() -> ImuReading`, `.ultrasonic.read() -> ObstacleDetection | None`, `.camera.read() -> tuple[str, float] | None` — structurally satisfying `papaya_mission.sensor_hub.SensorHub`. Task 5 passes `world.sensor_hub` straight to `MissionRuntime(sensor_hub=...)`.

- [ ] **Step 1: Write the failing tests**

Append to `test_digital_twin.py`:

```python
from papaya_mission.geo_utils import METERS_PER_DEGREE_LAT


def test_gps_unavailable_returns_none():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0)
    world.gps_available = False

    assert world.sensor_hub.gps.read() is None


def test_gps_reading_wanders_within_accuracy_but_never_exact():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0, gps_accuracy_m=5.0, rng_seed=42)

    readings = [world.sensor_hub.gps.read() for _ in range(20)]

    assert all(r is not None for r in readings)
    assert all(r.accuracy_m == 5.0 for r in readings)
    for r in readings:
        error_m = flat_earth_distance_m((world.lon, world.lat), (r.lon, r.lat))
        assert error_m <= 5.0 + 1e-9
    # Not every reading is the true position -- it genuinely wanders.
    assert any((r.lat, r.lon) != (world.lat, world.lon) for r in readings)


def test_gps_reading_is_reproducible_for_the_same_seed():
    world_a = TwinWorld(start_lat=38.0, start_lon=-85.0, rng_seed=7)
    world_b = TwinWorld(start_lat=38.0, start_lon=-85.0, rng_seed=7)

    readings_a = [world_a.sensor_hub.gps.read() for _ in range(5)]
    readings_b = [world_b.sensor_hub.gps.read() for _ in range(5)]

    assert readings_a == readings_b


def test_imu_reflects_current_heading_and_derived_acceleration():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0)
    world.step(dt_s=1.0, heading_deg=45.0, speed_mps=2.0)

    reading = world.sensor_hub.imu.read()

    assert reading.heading_deg == 45.0
    assert reading.forward_acceleration_mps2 == 2.0
    assert reading.timestamp == world.clock_s


def test_ultrasonic_and_camera_agree_on_the_same_in_view_obstacle():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0)
    obstacle_lat, obstacle_lon = project_position(38.0, -85.0, bearing_deg=0.0, distance_m=3.0)
    world.obstacles.append(TwinObstacle(
        lat=obstacle_lat, lon=obstacle_lon, collision_radius_m=0.3,
        classified_type="barrel", classification_confidence=0.9,
    ))
    world.point_mast_at(0.0)

    detection = world.sensor_hub.ultrasonic.read()
    classification = world.sensor_hub.camera.read()

    assert detection is not None
    assert detection.relative_bearing_deg == world.mast_angle_deg
    assert math.isclose(detection.range_m, 3.0, rel_tol=1e-6)
    assert classification == ("barrel", 0.9)


def test_ultrasonic_and_camera_both_none_when_nothing_in_view():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0)

    assert world.sensor_hub.ultrasonic.read() is None
    assert world.sensor_hub.camera.read() is None
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_digital_twin.py -v`
Expected: FAIL — `AttributeError: 'TwinWorld' object has no attribute 'sensor_hub'`

- [ ] **Step 3: Write the implementation**

Add to `digital_twin.py`'s imports:

```python
from papaya_mission.position_fusion import GpsFix, ImuReading
from papaya_mission.sensor_hub import ObstacleDetection
```

Add these adapter classes after `TwinObstacle` and before `TwinWorld`:

```python
class _TwinGpsSource:
    def __init__(self, world: TwinWorld) -> None:
        self._world = world

    def read(self) -> GpsFix | None:
        if not self._world.gps_available:
            return None
        # Uniform sample inside a disk of radius gps_accuracy_m: sqrt(random())
        # for the radius (not a plain uniform radius, which would bias
        # samples toward the center) and a uniform angle.
        radius_m = self._world.gps_accuracy_m * math.sqrt(self._world._rng.random())
        angle_rad = self._world._rng.uniform(0.0, 2 * math.pi)
        north_m = radius_m * math.cos(angle_rad)
        east_m = radius_m * math.sin(angle_rad)
        offset_lat = north_m / geo_utils.METERS_PER_DEGREE_LAT
        offset_lon = east_m / (geo_utils.METERS_PER_DEGREE_LAT * math.cos(math.radians(self._world.lat)))
        return GpsFix(
            lat=self._world.lat + offset_lat,
            lon=self._world.lon + offset_lon,
            accuracy_m=self._world.gps_accuracy_m,
            timestamp=self._world.clock_s,
        )


class _TwinImuSource:
    def __init__(self, world: TwinWorld) -> None:
        self._world = world

    def read(self) -> ImuReading:
        return ImuReading(
            heading_deg=self._world.heading_deg,
            forward_acceleration_mps2=self._world._acceleration_mps2,
            timestamp=self._world.clock_s,
        )


class _TwinUltrasonicSource:
    def __init__(self, world: TwinWorld) -> None:
        self._world = world

    def read(self) -> ObstacleDetection | None:
        obstacle = self._world._obstacle_in_view()
        if obstacle is None:
            return None
        _, range_m = self._world._bearing_and_range_to(obstacle.lat, obstacle.lon)
        return ObstacleDetection(relative_bearing_deg=self._world.mast_angle_deg, range_m=range_m)


class _TwinCameraSource:
    def __init__(self, world: TwinWorld) -> None:
        self._world = world

    def read(self) -> tuple[str, float] | None:
        obstacle = self._world._obstacle_in_view()
        if obstacle is None:
            return None
        return (obstacle.classified_type, obstacle.classification_confidence)


class _TwinSensorHub:
    def __init__(self, world: TwinWorld) -> None:
        self.gps = _TwinGpsSource(world)
        self.imu = _TwinImuSource(world)
        self.ultrasonic = _TwinUltrasonicSource(world)
        self.camera = _TwinCameraSource(world)
```

Then, as the last line of `TwinWorld.__init__` (after `self.ota_triggers = []`):

```python
        self.sensor_hub = _TwinSensorHub(self)
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_digital_twin.py -v`
Expected: PASS (19 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/digital_twin.py pathfinder-autonomous/pi-mission/tests/test_digital_twin.py
git commit -m "feat(pi-mission): add twin SensorHub adapters with GPS jitter"
```

---

### Task 4: Esp32Link adapter

**Files:**
- Modify: `pathfinder-autonomous/pi-mission/papaya_mission/digital_twin.py`
- Modify: `pathfinder-autonomous/pi-mission/tests/test_digital_twin.py`

**Interfaces:**
- Consumes: `TwinWorld._pending_bump_events`, `TwinWorld._halted_on_contact`, `TwinWorld.speed_mps`, `TwinWorld.max_speed_mps`, `TwinWorld.geofence_updates_sent`, `TwinWorld.ota_triggers` from Task 1.
- Produces: `TwinWorld.esp32_link` attribute (added as the last line of `TwinWorld.__init__`), an object with `.poll_bump_events() -> list[BumpEvent]`, `.status() -> Esp32Status`, `.read_drive_status() -> DriveStatus`, `.send_geofence_update(exclusion_zone_ids: list[str]) -> None`, `.trigger_ota(firmware_path: str) -> None` — structurally satisfying `papaya_mission.esp32_link.Esp32Link`. Task 5 passes `world.esp32_link` straight to `MissionRuntime(esp32_link=...)`.

- [ ] **Step 1: Write the failing tests**

Append to `test_digital_twin.py`:

```python
def test_poll_bump_events_drains_the_pending_queue():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0)
    obstacle_lat, obstacle_lon = project_position(38.0, -85.0, bearing_deg=0.0, distance_m=1.0)
    world.obstacles.append(TwinObstacle(
        lat=obstacle_lat, lon=obstacle_lon, collision_radius_m=0.5,
        classified_type="unknown", classification_confidence=0.0,
    ))
    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=1.0)  # triggers one bump event

    events = world.esp32_link.poll_bump_events()
    assert len(events) == 1
    assert world.esp32_link.poll_bump_events() == []


def test_status_reflects_halted_on_contact_until_cleared():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0)
    assert world.esp32_link.status().halted_on_contact is False

    obstacle_lat, obstacle_lon = project_position(38.0, -85.0, bearing_deg=0.0, distance_m=1.0)
    world.obstacles.append(TwinObstacle(
        lat=obstacle_lat, lon=obstacle_lon, collision_radius_m=0.5,
        classified_type="unknown", classification_confidence=0.0,
    ))
    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=1.0)
    assert world.esp32_link.status().halted_on_contact is True

    world.clear_halt()
    assert world.esp32_link.status().halted_on_contact is False


def test_read_drive_status_normalizes_speed_against_max_speed():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0, max_speed_mps=2.0)
    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=1.0)

    status = world.esp32_link.read_drive_status()

    assert status.servo_positions_deg == {}
    assert status.throttle_position == 0.5


def test_read_drive_status_clamps_throttle_to_one():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0, max_speed_mps=1.0)
    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=5.0)  # scenario asked for more than max_speed_mps

    assert world.esp32_link.read_drive_status().throttle_position == 1.0


def test_send_geofence_update_and_trigger_ota_are_recorded():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0)

    world.esp32_link.send_geofence_update(["zone-1"])
    world.esp32_link.trigger_ota("/firmware/v2.bin")

    assert world.geofence_updates_sent == [["zone-1"]]
    assert world.ota_triggers == ["/firmware/v2.bin"]
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_digital_twin.py -v`
Expected: FAIL — `AttributeError: 'TwinWorld' object has no attribute 'esp32_link'`

- [ ] **Step 3: Write the implementation**

Add to `digital_twin.py`'s imports:

```python
from papaya_mission.esp32_link import BumpEvent, DriveStatus, Esp32Status
```

(replacing the existing `from papaya_mission.esp32_link import BumpEvent` line from Task 1 with this wider one).

Add this adapter class after `_TwinSensorHub`:

```python
class _TwinEsp32Link:
    def __init__(self, world: TwinWorld) -> None:
        self._world = world

    def poll_bump_events(self) -> list[BumpEvent]:
        events, self._world._pending_bump_events = self._world._pending_bump_events, []
        return events

    def status(self) -> Esp32Status:
        return Esp32Status(halted_on_contact=self._world._halted_on_contact)

    def read_drive_status(self) -> DriveStatus:
        # No steering-servo model exists yet -- same "placeholder pending
        # final wiring" caveat as esp32_link.py's own DriveStatus docstring.
        throttle = self._world.speed_mps / self._world.max_speed_mps
        throttle = max(-1.0, min(1.0, throttle))
        return DriveStatus(servo_positions_deg={}, throttle_position=throttle)

    def send_geofence_update(self, exclusion_zone_ids: list[str]) -> None:
        self._world.geofence_updates_sent.append(exclusion_zone_ids)

    def trigger_ota(self, firmware_path: str) -> None:
        self._world.ota_triggers.append(firmware_path)
```

Then, as the last line of `TwinWorld.__init__` (after `self.sensor_hub = _TwinSensorHub(self)`):

```python
        self.esp32_link = _TwinEsp32Link(self)
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_digital_twin.py -v`
Expected: PASS (24 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/digital_twin.py pathfinder-autonomous/pi-mission/tests/test_digital_twin.py
git commit -m "feat(pi-mission): add twin Esp32Link adapter"
```

---

### Task 5: End-to-end scenario tests against a real MissionRuntime

**Files:**
- Create: `pathfinder-autonomous/pi-mission/tests/test_digital_twin_scenarios.py`

**Interfaces:**
- Consumes: `TwinWorld`, `TwinObstacle` from Tasks 1-4; `papaya_mission.runtime.MissionRuntime`; `papaya_mission.local_store.list_unsynced_obstacles`; `papaya_mission.geo_utils.project_position`. Follows the same `_make_started_runtime` fixture pattern as `tests/test_runtime_tick_sensing.py`.
- Produces: nothing consumed by later tasks — this is the final task in the plan.

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_digital_twin_scenarios.py
import httpx

from papaya_mission import local_store
from papaya_mission.digital_twin import TwinObstacle, TwinWorld
from papaya_mission.geo_utils import project_position
from papaya_mission.runtime import MissionRuntime

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


def _make_started_runtime(tmp_path, world: TwinWorld) -> MissionRuntime:
    rover = {"_id": "rover-1", "name": "George", "length_m": 0.6, "turn_style": "spin_in_place"}
    inclusive = {"_id": "fence-1", "type": "inclusive", "boundary": {"type": "Polygon", "coordinates": [FIELD_RING]}}
    client = httpx.Client(transport=httpx.MockTransport(_handler(rover, [inclusive])))
    runtime = MissionRuntime(
        rover_id="rover-1",
        backend_base_url="http://backend.local",
        local_db_path=str(tmp_path / "test.db"),
        sensor_hub=world.sensor_hub,
        esp32_link=world.esp32_link,
        http_client=client,
    )
    runtime.startup()
    runtime.handle_start_sweep({"geofence_id": "fence-1"})
    return runtime


def test_ultrasonic_and_camera_agree_on_same_forward_obstacle(tmp_path):
    world = TwinWorld(start_lat=38.05, start_lon=-85.0)
    obstacle_lat, obstacle_lon = project_position(38.05, -85.0, bearing_deg=0.0, distance_m=3.0)
    world.obstacles.append(TwinObstacle(
        lat=obstacle_lat, lon=obstacle_lon, collision_radius_m=0.3,
        classified_type="barrel", classification_confidence=0.9,
    ))
    runtime = _make_started_runtime(tmp_path, world)

    world.point_mast_at(world.mast_sweep_limit_deg)  # look away for the seed tick
    runtime.tick()  # seeds position_fusion from the twin's GPS fix, no detection yet

    world.point_mast_at(0.0)  # now look straight at the obstacle
    runtime.tick()

    saved = local_store.list_unsynced_obstacles(runtime.conn)
    assert len(saved) == 1
    assert saved[0]["type"] == "barrel"
    assert saved[0]["status"] == "permanent-pending"
    assert saved[0]["detection_method"] == "ultrasonic+camera"


def test_bump_contact_halts_movement_and_is_recorded(tmp_path):
    world = TwinWorld(start_lat=38.05, start_lon=-85.0)
    world.point_mast_at(world.mast_sweep_limit_deg)  # keep the sweep away from the obstacle throughout
    obstacle_lat, obstacle_lon = project_position(38.05, -85.0, bearing_deg=0.0, distance_m=1.0)
    world.obstacles.append(TwinObstacle(
        lat=obstacle_lat, lon=obstacle_lon, collision_radius_m=0.5,
        classified_type="unknown", classification_confidence=0.0,
    ))
    runtime = _make_started_runtime(tmp_path, world)
    runtime.tick()  # seeds position_fusion; mast is pointed away, so no ultrasonic pairing yet

    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=1.0)  # drives 1m north, straight into the obstacle
    assert world._halted_on_contact is True

    position_before_next_step = (world.lat, world.lon)
    runtime.tick()  # polls the bump event, saves a contact-only obstacle

    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=1.0)  # halted -- should not move further
    assert (world.lat, world.lon) == position_before_next_step

    saved = local_store.list_unsynced_obstacles(runtime.conn)
    assert len(saved) == 1
    assert saved[0]["detection_method"] == "contact-only"
    assert saved[0]["status"] == "permanent-pending"


def test_gps_unavailable_triggers_stop_and_alert(tmp_path):
    world = TwinWorld(start_lat=38.05, start_lon=-85.0)
    runtime = _make_started_runtime(tmp_path, world)
    runtime.tick()  # seeds position_fusion from a real fix

    world.gps_available = False
    runtime._last_gps_fix_monotonic -= 31.0  # simulate 31s of GPS silence, past the 30s grace period
    runtime.tick()

    assert runtime.mission_alert == "gps_stop_and_alert"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_digital_twin_scenarios.py -v`
Expected: FAIL if any of Tasks 1-4 are incomplete (`AttributeError`/`ImportError`); if Tasks 1-4 are already done and this is a genuine first run, these should already PASS since no new production code is introduced by this task — treat an unexpected failure here as a real integration bug to fix, not a step to skip.

- [ ] **Step 3: (No new implementation)**

This task adds no new code to `digital_twin.py` — it only exercises the adapters built in Tasks 1-4 against a real `MissionRuntime`, the same way `tests/test_runtime_tick_sensing.py` exercises `SimulatedSensorHub`/`FakeEsp32Link`.

- [ ] **Step 4: Run the full test suite and verify everything passes**

Run: `pytest -v` (from `pathfinder-autonomous/pi-mission/`)
Expected: PASS — all prior MP-1 tests plus the new `test_digital_twin.py` (24 tests) and `test_digital_twin_scenarios.py` (3 tests).

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/tests/test_digital_twin_scenarios.py
git commit -m "test(pi-mission): add end-to-end digital-twin scenarios against MissionRuntime"
```
