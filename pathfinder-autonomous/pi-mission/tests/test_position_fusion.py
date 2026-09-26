import math

import pytest

from papaya_mission.geo_utils import METERS_PER_DEGREE_LAT
from papaya_mission.position_fusion import (
    GpsFix,
    ImuReading,
    PositionEstimate,
    PositionFusion,
)


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


def test_as_lon_lat_returns_lon_first():
    """The geometry modules take raw (lon, lat) tuples while this module
    uses named fields; this bridge exists so callers never hand-build the
    tuple in the wrong order.
    """
    estimate = PositionEstimate(
        lat=38.0, lon=-85.0, heading_deg=0.0, error_radius_m=2.0, timestamp=0.0
    )

    assert estimate.as_lon_lat() == (-85.0, 38.0)


def test_positional_construction_is_rejected():
    """Positional args made GpsFix(*lon_lat_tuple, ...) a silent lat/lon
    swap. kw_only makes it a TypeError instead.
    """
    with pytest.raises(TypeError):
        GpsFix(38.0, -85.0, 2.0, 0.0)


def test_longitude_update_uses_the_pre_move_latitude():
    """The cos() term scaling the longitude delta must use the latitude the
    rover started the step at, not the one it just moved to. An oversized
    step exaggerates what is otherwise a sub-millimeter ordering error.
    """
    start_lat, start_lon = 38.0, -85.0
    fusion = PositionFusion(
        GpsFix(lat=start_lat, lon=start_lon, accuracy_m=2.0, timestamp=0.0)
    )

    dt, accel, heading = 100.0, 2.0, 45.0
    estimate = fusion.on_imu_reading(
        ImuReading(
            heading_deg=heading,
            forward_acceleration_mps2=accel,
            timestamp=dt,
        )
    )

    distance_m = (accel * dt) * dt
    heading_rad = math.radians(heading)
    expected_lon = start_lon + (distance_m * math.sin(heading_rad)) / (
        METERS_PER_DEGREE_LAT * math.cos(math.radians(start_lat))
    )

    assert math.isclose(estimate.lon, expected_lon, rel_tol=1e-12)


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
