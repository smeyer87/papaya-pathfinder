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

Unlike SimulatedSensorHub's consume-once scripted fields, the twin's
ultrasonic/camera sources are stateless derivations from world state: they
report an in-view obstacle fresh on every single read, for as long as it
stays inside the mast's beam and range -- not just once.
MissionRuntime._detect_obstacles (unmodified, existing code) has no
per-tick deduplication of its own, so a scenario that leaves an obstacle in view
across multiple ticks will see one new saved obstacle row per tick it was
detected, not one row total. This is existing MissionRuntime behavior, not
something the twin works around -- a scenario author who wants exactly one
saved row should either point the mast away after the first detecting
tick, or assert on "at least one row of the right type" rather than
"exactly one row."
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from shapely.geometry import Polygon

from papaya_mission import geo_utils
from papaya_mission.esp32_link import BumpEvent, DriveStatus, Esp32Status
from papaya_mission.geo_utils import flat_earth_distance_m, project_position
from papaya_mission.position_fusion import GpsFix, ImuReading
from papaya_mission.sensor_hub import ObstacleDetection


@dataclass(frozen=True, kw_only=True)
class TwinObstacle:
    lat: float
    lon: float
    collision_radius_m: float
    classified_type: str
    classification_confidence: float


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
        # heading_deg % 360.0, not the raw attribute: step() normalizes
        # into [0, 360) when it sets self.heading_deg, but world.heading_deg
        # is a public, directly-mutable attribute (scenario/test code does
        # assign to it directly), and ImuReading.__post_init__ raises
        # ValueError if heading_deg is ever out of [0.0, 360.0). Normalizing
        # here means a read can never crash for that reason.
        return ImuReading(
            heading_deg=self._world.heading_deg % 360.0,
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
        # Scenario-side bookkeeping only -- nothing in digital_twin.py ever
        # reads this. It exists so a scenario can hand the same Polygon
        # list to other production code (e.g. find_intruded_exclusion)
        # alongside the twin; appending to it has no effect on the twin's
        # own behavior.
        self.exclusion_zones: list[Polygon] = []

        self._halted_on_contact = False
        # Real references (not id()s) on purpose: CPython reuses freed
        # memory addresses, so a set of id(obstacle) can collide between an
        # already-removed obstacle and a brand-new one placed at the same
        # collision point (e.g. a scenario clears world.obstacles and
        # appends a fresh TwinObstacle) and silently swallow a new bump
        # event. Holding the actual object keeps its id alive and
        # comparisons are done via identity (`is`), not id() hashing.
        self._contacted_obstacles: list[TwinObstacle] = []
        self._pending_bump_events: list[BumpEvent] = []
        self.geofence_updates_sent: list[list[str]] = []
        self.ota_triggers: list[str] = []
        self.sensor_hub = _TwinSensorHub(self)
        self.esp32_link = _TwinEsp32Link(self)

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
        """Force the mast to point at relative_deg (clamped to
        +/-mast_sweep_limit_deg), overriding the autonomous sweep for this
        tick's sensor reads.

        Ordering matters: step() unconditionally advances the autonomous
        mast sweep (_advance_mast) on every call, so calling point_mast_at()
        *before* step() gets immediately undone by that tick's sweep
        advance -- the mast will NOT end up pointed where you asked. Call
        this *after* this tick's step() (or don't call step() at all this
        tick), immediately before the sensor reads that depend on the mast
        angle (i.e. right before runtime.tick()).
        """
        self.mast_angle_deg = max(-self.mast_sweep_limit_deg, min(self.mast_sweep_limit_deg, relative_deg))

    def clear_halt(self) -> None:
        self._halted_on_contact = False

    def _advance_mast(self, dt_s: float) -> None:
        # Caveat at extreme parameters: if mast_turn_rate_dps * dt_s exceeds
        # roughly 2 * mast_sweep_limit_deg, the clamp-and-reverse below can
        # bounce the mast between its two endpoints every tick without ever
        # passing through intermediate angles (e.g. never pointing dead
        # ahead). Harmless at the plan's documented defaults (30 dps, 60
        # deg limit, typical dt_s ~0.1-1.0s) -- just don't reintroduce it
        # silently if these parameters change.
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
        still_touching: list[TwinObstacle] = []
        for obstacle in self.obstacles:
            distance_m = flat_earth_distance_m((self.lon, self.lat), (obstacle.lon, obstacle.lat))
            if distance_m <= obstacle.collision_radius_m:
                still_touching.append(obstacle)
                if not any(o is obstacle for o in self._contacted_obstacles):
                    self._pending_bump_events.append(BumpEvent(detected_at=now))
                    self._halted_on_contact = True
        self._contacted_obstacles = still_touching

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
        step_distance_m = speed_mps * dt_s
        if step_distance_m <= 0:
            raise ValueError(
                f"drive_route requires speed_mps * dt_s > 0 to make progress "
                f"toward a waypoint (got speed_mps={speed_mps!r}, dt_s={dt_s!r}); "
                f"the loop would never terminate otherwise."
            )
        for target_lat, target_lon in waypoints:
            remaining_m = flat_earth_distance_m((self.lon, self.lat), (target_lon, target_lat))
            while remaining_m > 1e-6:
                relative_bearing_deg, _ = self._bearing_and_range_to(target_lat, target_lon)
                absolute_heading_deg = (self.heading_deg + relative_bearing_deg) % 360.0
                self.step(dt_s, heading_deg=absolute_heading_deg, speed_mps=speed_mps)
                if self._halted_on_contact:
                    # A bump halt froze position this tick (see step()) --
                    # keep iterating and we'd silently "complete" the route
                    # without ever having arrived. Abandon remaining waypoints.
                    return
                remaining_m -= step_distance_m
