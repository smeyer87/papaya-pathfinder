import pytest
from shapely.geometry import Polygon

from papaya_mission.coverage_pattern import generate_coverage_pattern

FIELD = Polygon(
    [
        (-85.001, 38.000),
        (-85.001, 38.001),
        (-85.000, 38.001),
        (-85.000, 38.000),
        (-85.001, 38.000),
    ]
)


def test_generates_multiple_rows_covering_the_field():
    waypoints = generate_coverage_pattern(FIELD, exclusions=[], row_spacing_m=20.0)

    assert len(waypoints) >= 4  # at least 2 rows x 2 endpoints each
    lats = [lat for _, lat in waypoints]
    assert min(lats) >= 38.000
    assert max(lats) <= 38.001


def test_rows_alternate_direction_boustrophedon():
    waypoints = generate_coverage_pattern(FIELD, exclusions=[], row_spacing_m=20.0)

    first_row = waypoints[0:2]
    assert first_row[0][0] < first_row[1][0]  # row 0: west to east

    second_row = waypoints[2:4]
    assert second_row[0][0] > second_row[1][0]  # row 1: east to west


def test_exclusion_zone_removes_covered_area():
    exclusion = Polygon(
        [
            (-85.0007, 38.0003),
            (-85.0007, 38.0007),
            (-85.0003, 38.0007),
            (-85.0003, 38.0003),
            (-85.0007, 38.0003),
        ]
    )

    waypoints = generate_coverage_pattern(FIELD, exclusions=[exclusion], row_spacing_m=20.0)

    for lon, lat in waypoints:
        assert not (-85.0007 < lon < -85.0003 and 38.0003 < lat < 38.0007)


def test_exclusion_covering_entire_field_yields_no_waypoints():
    full_cover = Polygon(
        [
            (-85.002, 37.999),
            (-85.002, 38.002),
            (-84.999, 38.002),
            (-84.999, 37.999),
            (-85.002, 37.999),
        ]
    )

    waypoints = generate_coverage_pattern(FIELD, exclusions=[full_cover], row_spacing_m=20.0)

    assert waypoints == []


def test_non_positive_row_spacing_raises_value_error():
    """Test that zero row_spacing_m raises ValueError."""
    with pytest.raises(ValueError, match="row_spacing_m must be positive"):
        generate_coverage_pattern(FIELD, exclusions=[], row_spacing_m=0.0)


def test_negative_row_spacing_raises_value_error():
    """Test that negative row_spacing_m raises ValueError."""
    with pytest.raises(ValueError, match="row_spacing_m must be positive"):
        generate_coverage_pattern(FIELD, exclusions=[], row_spacing_m=-5.0)
