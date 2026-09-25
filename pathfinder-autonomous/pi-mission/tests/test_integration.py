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
