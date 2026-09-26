from datetime import datetime, timezone

from shapely.geometry import LineString, Polygon

from papaya_mission.coverage_pattern import generate_coverage_pattern
from papaya_mission.exclusion_check import find_intruded_exclusion
from papaya_mission.exclusion_decision import decide_exclusion_response
from papaya_mission.gps_loss_decision import decide_gps_loss_response
from papaya_mission.row_spacing import derive_row_spacing_m
from papaya_mission.sweep_session import SweepSession, SweepSessionStatus

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
    # A real exclusion this time: the pond splits the rows that cross it,
    # so generate_coverage_pattern returns more legs than there are rows.
    legs = generate_coverage_pattern(FIELD, exclusions=[POND], row_spacing_m=row_spacing)
    assert len(legs) > 1, "expected the pond to split the pattern into several legs"

    # from_legs keeps the leg boundaries, so a consumer can tell a straight
    # drive (same leg) from a gap it must route around (leg boundary).
    session = SweepSession.from_legs(
        legs,
        id="sess-1",
        rover_id="rover-1",
        geofence_id="fence-1",
        started_at=START,
    )

    # The leg contract: consecutive waypoints within one leg are directly
    # drivable -- the straight line between them never enters the pond.
    # Consecutive waypoints in *different* legs may jump across it; that
    # gap is exactly why the leg boundary exists.
    for previous, current in zip(session.pattern, session.pattern[1:]):
        if previous.leg_index != current.leg_index:
            continue
        segment = LineString([previous.position, current.position])
        assert segment.intersection(POND).length == 0

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

    # And an exclusion-zone intrusion like this. The depth is reported in
    # meters, not degrees -- a regression to degree-space would be ~0.0002.
    exclusion_hit = find_intruded_exclusion((-85.0005, 38.0005), [POND])
    assert exclusion_hit is not None
    _, depth = exclusion_hit
    assert depth > 1.0
    assert decide_exclusion_response(depth, rover_length_m=0.6) == "wait_for_help"
