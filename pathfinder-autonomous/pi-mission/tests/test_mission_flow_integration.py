from datetime import datetime, timezone

from shapely.geometry import Polygon

from papaya_mission.coverage_pattern import generate_coverage_pattern
from papaya_mission.exclusion_check import find_intruded_exclusion
from papaya_mission.exclusion_decision import decide_exclusion_response
from papaya_mission.gps_loss_decision import decide_gps_loss_response
from papaya_mission.row_spacing import derive_row_spacing_m
from papaya_mission.sweep_session import SweepSession, SweepSessionStatus, Waypoint

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
START = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


def test_full_sweep_lifecycle_with_interruption_and_safety_decisions():
    row_spacing = derive_row_spacing_m(
        sensor_detection_width_m=20.0, turn_style="spin_in_place"
    )
    # generate_coverage_pattern returns a list of legs (contiguous drivable
    # polylines) rather than one flat path, since an exclusion zone can
    # split a row into two disconnected pieces. Flatten them for this test's
    # purposes -- SweepSession just needs a flat, contiguously-ordered
    # sequence of waypoints to track progress against.
    legs = generate_coverage_pattern(FIELD, exclusions=[], row_spacing_m=row_spacing)
    raw_pattern = [point for leg in legs for point in leg]
    pattern = [Waypoint(order=i, position=pos) for i, pos in enumerate(raw_pattern)]

    session = SweepSession(
        id="sess-1", rover_id="rover-1", geofence_id="fence-1", pattern=pattern, started_at=START
    )

    # Cover the first waypoint, then get interrupted (e.g. Bingo Fuel).
    session.mark_waypoint_complete(0)
    session.interrupt(at=START)
    assert session.status == SweepSessionStatus.INTERRUPTED

    # Resume and finish the rest.
    session.resume()
    for waypoint in session.remaining_waypoints:
        session.mark_waypoint_complete(waypoint.order)
    assert session.is_fully_covered
    session.complete(at=START)
    assert session.status == SweepSessionStatus.COMPLETED

    # A brief GPS dropout mid-sweep would have been handled like this:
    gps_response = decide_gps_loss_response(
        seconds_since_last_fix=3.0,
        current_error_radius_m=4.0,
        grace_period_s=10.0,
        max_error_radius_m=8.0,
    )
    assert gps_response == "continue_dead_reckoning"

    # And an exclusion-zone intrusion like this:
    exclusion_hit = find_intruded_exclusion((-85.0005, 38.0005), [POND])
    assert exclusion_hit is not None
    _, depth = exclusion_hit
    assert decide_exclusion_response(depth, rover_length_m=0.6) in (
        "auto_reverse",
        "wait_for_help",
    )
