"""The sweep-session state machine: tracks coverage-pattern progress
through start/interrupt/resume/complete, enabling MP-1's resume
capability. See design spec: Data Model -- Sweep session, Mission Flow.

Build a session from `generate_coverage_pattern()`'s output with
`SweepSession.from_legs()`, never by flattening its legs into one list:
the flatten loses the leg boundaries, and a leg boundary is exactly the
place where an exclusion zone sits between two waypoints.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class SweepSessionStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"


@dataclass(frozen=True)
class Waypoint:
    order: int
    position: tuple[float, float]  # (lon, lat)
    # Which contiguous leg of the coverage pattern this waypoint belongs
    # to. Two consecutive waypoints sharing a leg_index are directly
    # drivable in a straight line; a change of leg_index marks a gap an
    # exclusion zone created, which the caller must route around.
    leg_index: int = 0


class InvalidSweepSessionTransition(Exception):
    pass


@dataclass
class SweepSession:
    """One rover's progress through one coverage pattern.

    Prefer `from_legs()` to build a session from
    `generate_coverage_pattern()`'s leg list; construct `SweepSession(...)`
    directly only when rebuilding from already-persisted per-waypoint data.
    """

    id: str
    rover_id: str
    geofence_id: str
    pattern: list[Waypoint]
    status: SweepSessionStatus = SweepSessionStatus.IN_PROGRESS
    last_completed_waypoint_index: int = -1
    started_at: datetime | None = None
    interrupted_at: datetime | None = None
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.pattern:
            raise ValueError("pattern must contain at least one waypoint")
        expected_orders = list(range(len(self.pattern)))
        actual_orders = [wp.order for wp in self.pattern]
        if actual_orders != expected_orders:
            raise ValueError(
                f"pattern must have contiguous waypoint orders starting at 0, got {actual_orders}"
            )
        if not -1 <= self.last_completed_waypoint_index < len(self.pattern):
            raise ValueError(
                f"last_completed_waypoint_index must be between -1 and {len(self.pattern) - 1}, "
                f"got {self.last_completed_waypoint_index}"
            )

    @classmethod
    def from_legs(
        cls,
        legs: list[list[tuple[float, float]]],
        id: str,
        rover_id: str,
        geofence_id: str,
        started_at: datetime | None = None,
    ) -> "SweepSession":
        """Build a session directly from generate_coverage_pattern()'s leg
        list, tagging each Waypoint with which leg it belongs to so a
        caller can tell "drive straight to the next waypoint" (same leg)
        from "this leg just ended -- route around whatever split it from
        the next leg" (leg boundary), rather than blindly driving a
        straight line between every consecutive waypoint.
        """
        pattern = []
        order = 0
        for leg_index, leg in enumerate(legs):
            for position in leg:
                pattern.append(
                    Waypoint(order=order, position=position, leg_index=leg_index)
                )
                order += 1
        return cls(
            id=id,
            rover_id=rover_id,
            geofence_id=geofence_id,
            pattern=pattern,
            started_at=started_at,
        )

    @property
    def remaining_waypoints(self) -> list[Waypoint]:
        return [wp for wp in self.pattern if wp.order > self.last_completed_waypoint_index]

    @property
    def is_fully_covered(self) -> bool:
        return self.last_completed_waypoint_index >= len(self.pattern) - 1

    def mark_waypoint_complete(self, order: int) -> None:
        if self.status != SweepSessionStatus.IN_PROGRESS:
            raise InvalidSweepSessionTransition(
                f"cannot mark waypoint complete while session status is {self.status}"
            )
        if order >= len(self.pattern):
            raise InvalidSweepSessionTransition(
                f"waypoint order {order} is beyond the pattern's last order "
                f"{len(self.pattern) - 1}"
            )
        if order != self.last_completed_waypoint_index + 1:
            raise InvalidSweepSessionTransition(
                f"expected next waypoint order {self.last_completed_waypoint_index + 1}, got {order}"
            )
        self.last_completed_waypoint_index = order

    def interrupt(self, at: datetime) -> None:
        if self.status != SweepSessionStatus.IN_PROGRESS:
            raise InvalidSweepSessionTransition(
                f"cannot interrupt a session with status {self.status}"
            )
        self.status = SweepSessionStatus.INTERRUPTED
        self.interrupted_at = at

    def resume(self) -> None:
        if self.status != SweepSessionStatus.INTERRUPTED:
            raise InvalidSweepSessionTransition(
                f"cannot resume a session with status {self.status}"
            )
        self.status = SweepSessionStatus.IN_PROGRESS
        self.interrupted_at = None

    def complete(self, at: datetime) -> None:
        if self.status != SweepSessionStatus.IN_PROGRESS:
            raise InvalidSweepSessionTransition(
                f"cannot complete a session with status {self.status}"
            )
        if not self.is_fully_covered:
            raise InvalidSweepSessionTransition("cannot mark complete -- waypoints remain")
        self.status = SweepSessionStatus.COMPLETED
        self.completed_at = at
