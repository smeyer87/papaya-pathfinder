import math

from papaya_mission.digital_twin import TwinObstacle, TwinWorld
from papaya_mission.geo_utils import flat_earth_distance_m, project_position


def test_step_moves_rover_along_heading_by_project_position():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0)

    world.step(dt_s=2.0, heading_deg=90.0, speed_mps=1.5)

    expected_lat, expected_lon = project_position(38.0, -85.0, bearing_deg=90.0, distance_m=3.0)
    assert math.isclose(world.lat, expected_lat, abs_tol=1e-9)
    assert math.isclose(world.lon, expected_lon, abs_tol=1e-9)
    assert world.heading_deg == 90.0
    assert world.speed_mps == 1.5


def test_step_advances_clock_and_derives_acceleration():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0)

    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=2.0)

    assert world.clock_s == 1.0
    assert world._acceleration_mps2 == 2.0  # 0 -> 2.0 m/s over 1s

    world.step(dt_s=0.5, heading_deg=0.0, speed_mps=1.0)

    assert world.clock_s == 1.5
    assert world._acceleration_mps2 == -2.0  # 2.0 -> 1.0 m/s over 0.5s


def test_mast_sweeps_and_reverses_exactly_at_limits():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0, mast_sweep_limit_deg=10.0, mast_turn_rate_dps=10.0)

    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=0.0)  # 0 -> 10 (hits the limit)
    assert world.mast_angle_deg == 10.0

    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=0.0)  # reverses: 10 -> 0
    assert world.mast_angle_deg == 0.0

    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=0.0)  # keeps going: 0 -> -10
    assert world.mast_angle_deg == -10.0


def test_point_mast_at_sets_angle_and_clamps_to_sweep_limit():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0, mast_sweep_limit_deg=45.0)

    world.point_mast_at(20.0)
    assert world.mast_angle_deg == 20.0

    world.point_mast_at(90.0)
    assert world.mast_angle_deg == 45.0


def test_bump_contact_fires_once_on_entry_not_every_tick():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0)
    obstacle_lat, obstacle_lon = project_position(38.0, -85.0, bearing_deg=0.0, distance_m=1.0)
    world.obstacles.append(TwinObstacle(
        lat=obstacle_lat, lon=obstacle_lon, collision_radius_m=0.5,
        classified_type="unknown", classification_confidence=0.0,
    ))

    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=1.0)  # arrives exactly at the obstacle
    assert world._halted_on_contact is True
    assert len(world._pending_bump_events) == 1

    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=1.0)  # still touching -- no second event
    assert len(world._pending_bump_events) == 1


def test_halted_rover_does_not_move_until_cleared():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0)
    obstacle_lat, obstacle_lon = project_position(38.0, -85.0, bearing_deg=0.0, distance_m=1.0)
    world.obstacles.append(TwinObstacle(
        lat=obstacle_lat, lon=obstacle_lon, collision_radius_m=0.5,
        classified_type="unknown", classification_confidence=0.0,
    ))
    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=1.0)
    position_at_halt = (world.lat, world.lon)

    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=1.0)
    assert (world.lat, world.lon) == position_at_halt
    assert world.speed_mps == 0.0

    world.clear_halt()
    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=1.0)
    assert (world.lat, world.lon) != position_at_halt


def test_moving_away_and_back_retriggers_bump_contact():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0)
    obstacle_lat, obstacle_lon = project_position(38.0, -85.0, bearing_deg=0.0, distance_m=1.0)
    world.obstacles.append(TwinObstacle(
        lat=obstacle_lat, lon=obstacle_lon, collision_radius_m=0.5,
        classified_type="unknown", classification_confidence=0.0,
    ))
    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=1.0)  # contact #1
    assert len(world._pending_bump_events) == 1
    world.clear_halt()

    world.step(dt_s=1.0, heading_deg=180.0, speed_mps=2.0)  # back away, clear of the collision radius
    distance_away = flat_earth_distance_m((world.lon, world.lat), (obstacle_lon, obstacle_lat))
    assert distance_away > 0.5

    world.step(dt_s=1.0, heading_deg=0.0, speed_mps=2.0)  # drive back in -- contact #2
    assert len(world._pending_bump_events) == 2


def test_bearing_and_range_to_matches_project_position_inverse():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0)
    target_lat, target_lon = project_position(38.0, -85.0, bearing_deg=30.0, distance_m=50.0)

    relative_bearing_deg, range_m = world._bearing_and_range_to(target_lat, target_lon)

    assert math.isclose(relative_bearing_deg, 30.0, abs_tol=1e-6)  # heading_deg is 0.0 by default
    assert math.isclose(range_m, 50.0, rel_tol=1e-6)


def test_bearing_and_range_to_is_relative_to_current_heading():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0)
    world.heading_deg = 30.0
    target_lat, target_lon = project_position(38.0, -85.0, bearing_deg=30.0, distance_m=50.0)

    relative_bearing_deg, range_m = world._bearing_and_range_to(target_lat, target_lon)

    assert math.isclose(relative_bearing_deg, 0.0, abs_tol=1e-6)  # dead ahead once heading matches


def test_obstacle_in_view_requires_beam_and_range():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0, mast_beam_half_angle_deg=5.0, max_ultrasonic_range_m=10.0)
    near_ahead_lat, near_ahead_lon = project_position(38.0, -85.0, bearing_deg=0.0, distance_m=3.0)
    obstacle = TwinObstacle(
        lat=near_ahead_lat, lon=near_ahead_lon, collision_radius_m=0.3,
        classified_type="barrel", classification_confidence=0.9,
    )
    world.obstacles.append(obstacle)

    world.point_mast_at(0.0)
    assert world._obstacle_in_view() is obstacle

    world.point_mast_at(20.0)  # outside the 5-degree beam
    assert world._obstacle_in_view() is None


def test_obstacle_in_view_respects_max_range():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0, max_ultrasonic_range_m=2.0)
    far_ahead_lat, far_ahead_lon = project_position(38.0, -85.0, bearing_deg=0.0, distance_m=10.0)
    world.obstacles.append(TwinObstacle(
        lat=far_ahead_lat, lon=far_ahead_lon, collision_radius_m=0.3,
        classified_type="barrel", classification_confidence=0.9,
    ))

    world.point_mast_at(0.0)
    assert world._obstacle_in_view() is None


def test_obstacle_in_view_picks_the_nearest_of_several():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0)
    near_lat, near_lon = project_position(38.0, -85.0, bearing_deg=0.0, distance_m=2.0)
    far_lat, far_lon = project_position(38.0, -85.0, bearing_deg=0.0, distance_m=4.0)
    near = TwinObstacle(lat=near_lat, lon=near_lon, collision_radius_m=0.3, classified_type="post", classification_confidence=0.9)
    far = TwinObstacle(lat=far_lat, lon=far_lon, collision_radius_m=0.3, classified_type="barrel", classification_confidence=0.9)
    world.obstacles.extend([far, near])

    world.point_mast_at(0.0)
    assert world._obstacle_in_view() is near


def test_drive_route_arrives_near_each_waypoint_in_order():
    world = TwinWorld(start_lat=38.0, start_lon=-85.0)
    waypoint_a = project_position(38.0, -85.0, bearing_deg=0.0, distance_m=10.0)
    waypoint_b = project_position(*waypoint_a, bearing_deg=90.0, distance_m=10.0)

    world.drive_route([waypoint_a, waypoint_b], speed_mps=2.0, dt_s=1.0)

    assert flat_earth_distance_m((world.lon, world.lat), (waypoint_b[1], waypoint_b[0])) < 2.0
