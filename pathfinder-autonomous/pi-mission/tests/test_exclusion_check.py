from shapely.geometry import Polygon

from papaya_mission.exclusion_check import (
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
