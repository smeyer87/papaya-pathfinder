from datetime import datetime, timezone

import pytest

from papaya_mission.sweep_session import (
    InvalidSweepSessionTransition,
    SweepSession,
    SweepSessionStatus,
    Waypoint,
)

START = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


def _session(num_waypoints=3):
    pattern = [
        Waypoint(order=i, position=(-85.0 + i * 0.001, 38.0)) for i in range(num_waypoints)
    ]
    return SweepSession(
        id="sess-1", rover_id="rover-1", geofence_id="fence-1", pattern=pattern, started_at=START
    )


def test_new_session_has_no_completed_waypoints():
    session = _session()

    assert session.last_completed_waypoint_index == -1
    assert len(session.remaining_waypoints) == 3
    assert session.is_fully_covered is False


def test_mark_waypoint_complete_advances_progress():
    session = _session()

    session.mark_waypoint_complete(0)

    assert session.last_completed_waypoint_index == 0
    assert len(session.remaining_waypoints) == 2


def test_mark_waypoint_complete_rejects_out_of_order():
    session = _session()

    with pytest.raises(InvalidSweepSessionTransition):
        session.mark_waypoint_complete(1)  # skipped 0


def test_completing_all_waypoints_sets_is_fully_covered():
    session = _session(num_waypoints=2)

    session.mark_waypoint_complete(0)
    session.mark_waypoint_complete(1)

    assert session.is_fully_covered is True
    assert session.remaining_waypoints == []


def test_interrupt_and_resume_round_trip():
    session = _session()
    session.mark_waypoint_complete(0)

    session.interrupt(at=START)
    assert session.status == SweepSessionStatus.INTERRUPTED
    assert session.interrupted_at == START

    session.resume()
    assert session.status == SweepSessionStatus.IN_PROGRESS
    assert session.interrupted_at is None
    assert session.last_completed_waypoint_index == 0  # progress preserved


def test_cannot_interrupt_a_session_that_is_not_in_progress():
    session = _session()
    session.interrupt(at=START)

    with pytest.raises(InvalidSweepSessionTransition):
        session.interrupt(at=START)


def test_cannot_resume_a_session_that_is_not_interrupted():
    session = _session()

    with pytest.raises(InvalidSweepSessionTransition):
        session.resume()


def test_complete_requires_full_coverage():
    session = _session()

    with pytest.raises(InvalidSweepSessionTransition):
        session.complete(at=START)


def test_complete_succeeds_once_fully_covered():
    session = _session(num_waypoints=1)
    session.mark_waypoint_complete(0)

    session.complete(at=START)

    assert session.status == SweepSessionStatus.COMPLETED
    assert session.completed_at == START


def test_cannot_complete_a_session_that_is_already_completed():
    session = _session(num_waypoints=1)
    session.mark_waypoint_complete(0)
    session.complete(at=START)

    with pytest.raises(InvalidSweepSessionTransition):
        session.complete(at=START)


def test_cannot_complete_directly_from_interrupted_without_resuming():
    session = _session(num_waypoints=1)
    session.mark_waypoint_complete(0)
    session.interrupt(at=START)

    with pytest.raises(InvalidSweepSessionTransition):
        session.complete(at=START)


def test_empty_pattern_is_rejected():
    with pytest.raises(ValueError):
        SweepSession(
            id="sess-1",
            rover_id="rover-1",
            geofence_id="fence-1",
            pattern=[],
            started_at=START,
        )


def test_mark_waypoint_complete_rejects_order_beyond_pattern_length():
    session = _session(num_waypoints=1)
    session.mark_waypoint_complete(0)

    with pytest.raises(InvalidSweepSessionTransition):
        session.mark_waypoint_complete(1)  # no waypoint with order=1 exists


def test_out_of_range_last_completed_waypoint_index_is_rejected():
    pattern = [Waypoint(order=i, position=(-85.0 + i * 0.001, 38.0)) for i in range(3)]

    with pytest.raises(ValueError):
        SweepSession(
            id="sess-1",
            rover_id="rover-1",
            geofence_id="fence-1",
            pattern=pattern,
            last_completed_waypoint_index=5,
            started_at=START,
        )


def test_from_legs_tags_waypoints_with_their_leg_index():
    legs = [
        [(-85.0, 38.0), (-85.0005, 38.0)],
        [(-85.0008, 38.0), (-85.001, 38.0), (-85.0012, 38.0)],
    ]

    session = SweepSession.from_legs(
        legs,
        id="sess-1",
        rover_id="rover-1",
        geofence_id="fence-1",
        started_at=START,
    )

    assert [wp.order for wp in session.pattern] == [0, 1, 2, 3, 4]
    assert [wp.leg_index for wp in session.pattern] == [0, 0, 1, 1, 1]
    assert session.pattern[2].position == (-85.0008, 38.0)
    assert session.status == SweepSessionStatus.IN_PROGRESS
    assert session.started_at == START


def test_waypoint_leg_index_defaults_to_zero():
    assert Waypoint(order=0, position=(-85.0, 38.0)).leg_index == 0


def test_non_contiguous_pattern_orders_are_rejected():
    pattern = [
        Waypoint(order=0, position=(-85.0, 38.0)),
        Waypoint(order=2, position=(-85.0, 38.0)),
    ]

    with pytest.raises(ValueError):
        SweepSession(
            id="sess-1",
            rover_id="rover-1",
            geofence_id="fence-1",
            pattern=pattern,
            started_at=START,
        )
