"""The sweep-session state machine: tracks coverage-pattern progress
through start/interrupt/resume/complete, enabling MP-1's resume
capability. See design spec: Data Model -- Sweep session, Mission Flow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
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


class InvalidSweepSessionTransition(Exception):
    pass


@dataclass
class SweepSession:
    id: str
    rover_id: str
    geofence_id: str
    pattern: list[Waypoint]
    status: SweepSessionStatus = SweepSessionStatus.IN_PROGRESS
    last_completed_waypoint_index: int = -1
    started_at: datetime | None = None
    interrupted_at: datetime | None = None
    completed_at: datetime | None = None

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
        if not self.is_fully_covered:
            raise InvalidSweepSessionTransition("cannot mark complete -- waypoints remain")
        self.status = SweepSessionStatus.COMPLETED
        self.completed_at = at
