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
