"""The Pi<->ESP32 contract Mission Runtime depends on. The ESP32 owns
bump-sensor safety autonomously (hardware interrupt cuts the drive
train directly, no Pi round-trip) -- this interface never commands a
stop, it only ever reports one that already happened. See design
notes: Bump-sensor safety ownership.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class BumpEvent:
    detected_at: datetime


@dataclass(frozen=True)
class Esp32Status:
    halted_on_contact: bool


class Esp32Link(Protocol):
    def poll_bump_events(self) -> list[BumpEvent]: ...
    def status(self) -> Esp32Status: ...
    def send_geofence_update(self, exclusion_zone_ids: list[str]) -> None: ...
    def trigger_ota(self, firmware_path: str) -> None: ...


@dataclass
class FakeEsp32Link:
    """In-memory fake for tests."""

    _scripted_bump_events: list[BumpEvent] = field(default_factory=list)
    _scripted_status: Esp32Status = field(default_factory=lambda: Esp32Status(halted_on_contact=False))
    geofence_updates_sent: list[list[str]] = field(default_factory=list)
    ota_triggers: list[str] = field(default_factory=list)

    def script_bump_events(self, events: list[BumpEvent]) -> None:
        self._scripted_bump_events = list(events)

    def script_status(self, status: Esp32Status) -> None:
        self._scripted_status = status

    def poll_bump_events(self) -> list[BumpEvent]:
        events, self._scripted_bump_events = self._scripted_bump_events, []
        return events

    def status(self) -> Esp32Status:
        return self._scripted_status

    def send_geofence_update(self, exclusion_zone_ids: list[str]) -> None:
        self.geofence_updates_sent.append(exclusion_zone_ids)

    def trigger_ota(self, firmware_path: str) -> None:
        self.ota_triggers.append(firmware_path)
