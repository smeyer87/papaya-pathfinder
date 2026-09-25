import math

from papaya_mission.geo_utils import flat_earth_distance_m, project_position


def test_project_position_north_increases_latitude():
    new_lat, new_lon = project_position(lat=38.0, lon=-85.0, bearing_deg=0.0, distance_m=100.0)

    assert new_lat > 38.0
    assert math.isclose(new_lon, -85.0, abs_tol=1e-9)


def test_project_position_east_increases_longitude():
    new_lat, new_lon = project_position(lat=38.0, lon=-85.0, bearing_deg=90.0, distance_m=100.0)

    assert math.isclose(new_lat, 38.0, abs_tol=1e-9)
    assert new_lon > -85.0


def test_project_position_zero_distance_is_a_no_op():
    new_lat, new_lon = project_position(lat=38.0, lon=-85.0, bearing_deg=45.0, distance_m=0.0)

    assert new_lat == 38.0
    assert new_lon == -85.0


def test_flat_earth_distance_between_identical_points_is_zero():
    assert flat_earth_distance_m((-85.0, 38.0), (-85.0, 38.0)) == 0.0


def test_flat_earth_distance_roughly_matches_meters_per_degree():
    distance = flat_earth_distance_m((-85.0, 38.0), (-85.0, 39.0))  # 1 degree of latitude

    assert math.isclose(distance, 111_320.0, rel_tol=0.01)
