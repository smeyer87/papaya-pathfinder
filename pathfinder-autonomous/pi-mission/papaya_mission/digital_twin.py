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

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from shapely.geometry import Polygon

from papaya_mission import geo_utils
from papaya_mission.esp32_link import BumpEvent
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
        self.sensor_hub = _TwinSensorHub(self)

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
            while remaining_m > 1e-6:
                relative_bearing_deg, _ = self._bearing_and_range_to(target_lat, target_lon)
                absolute_heading_deg = (self.heading_deg + relative_bearing_deg) % 360.0
                self.step(dt_s, heading_deg=absolute_heading_deg, speed_mps=speed_mps)
                remaining_m -= step_distance_m
