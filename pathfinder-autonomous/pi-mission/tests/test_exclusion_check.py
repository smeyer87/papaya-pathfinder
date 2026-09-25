import math

from shapely.geometry import Polygon

from papaya_mission.exclusion_check import (
    METERS_PER_DEGREE_LAT,
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


def test_east_west_depth_accounts_for_longitude_compression():
    """A degree of longitude is METERS_PER_DEGREE_LAT * cos(lat) wide, not
    METERS_PER_DEGREE_LAT. Measuring an east-west intrusion in raw degrees
    overstated the depth by 27% at this latitude.
    """
    # Tall and narrow, so the nearest boundary is the west wall.
    tall_box = Polygon(
        [
            (-85.001, 38.000),
            (-85.001, 38.010),
            (-85.000, 38.010),
            (-85.000, 38.000),
            (-85.001, 38.000),
        ]
    )
    position = (-85.0009, 38.005)  # 0.0001 deg east of the west wall

    depth = exclusion_intrusion_depth_m(position, tall_box)

    expected_m = 0.0001 * METERS_PER_DEGREE_LAT * math.cos(math.radians(38.005))
    assert math.isclose(depth, expected_m, rel_tol=1e-6)
    assert math.isclose(expected_m, 8.77, abs_tol=0.01)
    # ...and definitively not the old uncompressed 11.132m.
    assert depth < 11.0


def test_depth_is_measured_to_a_nearby_hole_wall_not_the_far_outer_edge():
    """`.exterior` ignores interior rings, so a position standing just
    inside a donut's hole wall reported its distance to the far outer
    boundary instead -- a 40x overstatement.
    """
    shell = [
        (-85.010, 37.990),
        (-85.010, 38.010),
        (-84.990, 38.010),
        (-84.990, 37.990),
        (-85.010, 37.990),
    ]
    hole = [
        (-85.0005, 37.9995),
        (-85.0005, 38.0005),
        (-84.9995, 38.0005),
        (-84.9995, 37.9995),
        (-85.0005, 37.9995),
    ]
    donut = Polygon(shell, [hole])
    position = (-85.0006, 38.000)  # 0.0001 deg west of the hole's west wall

    depth = exclusion_intrusion_depth_m(position, donut)

    expected_m = 0.0001 * METERS_PER_DEGREE_LAT * math.cos(math.radians(38.000))
    assert math.isclose(depth, expected_m, rel_tol=1e-6)
    assert depth < 10.0  # not the ~800m distance to the outer shell


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
