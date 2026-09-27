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
