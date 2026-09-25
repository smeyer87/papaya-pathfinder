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
