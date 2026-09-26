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
