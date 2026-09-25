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


# These three are kw_only so that a positional call can never silently swap
# lat and lon -- e.g. `GpsFix(*some_lon_lat_tuple, 2.0, 0.0)`, which would
# produce a perfectly valid-looking fix on the wrong side of the equator.
# They are frozen because they are value objects: PositionFusion keeps its
# own mutable state in plain instance attributes, not in these.
@dataclass(frozen=True, kw_only=True)
class GpsFix:
    lat: float
    lon: float
    accuracy_m: float
    timestamp: float  # seconds; just needs consistent units with ImuReading


@dataclass(frozen=True, kw_only=True)
class ImuReading:
    heading_deg: float  # compass heading, 0 = north, clockwise positive
    forward_acceleration_mps2: float  # signed, positive = accelerating forward
    timestamp: float


@dataclass(frozen=True, kw_only=True)
class PositionEstimate:
    lat: float
    lon: float
    error_radius_m: float
    timestamp: float

    def as_lon_lat(self) -> tuple[float, float]:
        """This estimate as the (lon, lat) tuple `coverage_pattern` and
        `exclusion_check` expect. Use this rather than building the tuple
        by hand: a swapped `(lat, lon)` still makes a valid Point, it is
        just never inside any of this field's exclusion zones, so the
        mistake surfaces as quietly wrong answers instead of an error.
        """
        return (self.lon, self.lat)


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
        """Adopt a GPS fix as ground truth, discarding all dead-reckoned
        state accumulated since the last one.

        Note that `_velocity_mps` resets to zero here by design, not by
        oversight. Velocity is integrated from accelerometer readings with
        no wheel encoders to correct it, so by the time a fix arrives the
        carried-over value is mostly accumulated drift -- worse than
        starting from zero. Given MP-1's low travel speed and frequent
        fixes, treating each fix as a full reset of position, error radius
        *and* velocity is the intended simplification. Do not "fix" this
        by preserving velocity across fixes without first adding a
        velocity source worth preserving.
        """
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
        # Both deltas are derived from the latitude the step *started* at --
        # scaling the longitude delta by the post-move latitude would use a
        # cos() term for a position the rover has not reached yet.
        delta_lat = (distance_m * math.cos(heading_rad)) / METERS_PER_DEGREE_LAT
        delta_lon = (distance_m * math.sin(heading_rad)) / (
            METERS_PER_DEGREE_LAT * math.cos(math.radians(self._lat))
        )
        self._lat += delta_lat
        self._lon += delta_lon

        self._error_radius_m += self._drift_rate_m_per_s * dt
        self._last_timestamp = reading.timestamp

        return self.current_estimate
