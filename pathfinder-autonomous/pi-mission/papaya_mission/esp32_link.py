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


@dataclass(frozen=True)
class DriveStatus:
    """Reported drive-train state -- what the ESP32 is actually commanding
    the servos/throttle to right now, not what Mission Runtime last asked
    for. Exact servo key names are a placeholder pending the final
    steering-servo wiring/naming (this rover has multiple steering
    servos, per the PCB's J9-J12 header cluster) -- update once the ESP32
    firmware plan settles the real naming convention. Reported so ground
    control can correlate throttle/servo settings against observed speed
    and turn radius, which matters for tuning throttle sensitivity safely
    on real farm terrain.
    """

    servo_positions_deg: dict[str, float]
    throttle_position: float  # signed, -1.0 (full reverse) .. 1.0 (full forward), 0.0 = neutral


class Esp32Link(Protocol):
    """A real driver SHOULD avoid raising from these methods where
    possible -- return a safe default (an empty event list, a
    neutral/last-known status) rather than propagating a transient
    UART/I2C error. MissionRuntime also defensively catches exceptions
    around every call site into this Protocol as a second layer, so a
    flaky link degrades that tick rather than crashing the mission; this
    contract note is about which layer *should* handle it, not about that
    being the only thing standing between a flaky driver and a crash.
    """

    def poll_bump_events(self) -> list[BumpEvent]: ...
    def status(self) -> Esp32Status: ...
    def read_drive_status(self) -> DriveStatus: ...
    def send_geofence_update(self, exclusion_zone_ids: list[str]) -> None: ...
    def trigger_ota(self, firmware_path: str) -> None: ...


@dataclass
class FakeEsp32Link:
    """In-memory fake for tests."""

    _scripted_bump_events: list[BumpEvent] = field(default_factory=list)
    _scripted_status: Esp32Status = field(default_factory=lambda: Esp32Status(halted_on_contact=False))
    _scripted_drive_status: DriveStatus = field(
        default_factory=lambda: DriveStatus(servo_positions_deg={}, throttle_position=0.0)
    )
    geofence_updates_sent: list[list[str]] = field(default_factory=list)
    ota_triggers: list[str] = field(default_factory=list)

    def script_bump_events(self, events: list[BumpEvent]) -> None:
        self._scripted_bump_events = list(events)

    def script_status(self, status: Esp32Status) -> None:
        self._scripted_status = status

    def script_drive_status(self, status: DriveStatus) -> None:
        self._scripted_drive_status = status

    def poll_bump_events(self) -> list[BumpEvent]:
        events, self._scripted_bump_events = self._scripted_bump_events, []
        return events

    def status(self) -> Esp32Status:
        return self._scripted_status

    def read_drive_status(self) -> DriveStatus:
        # Not consume-once, unlike poll_bump_events: this reports current
        # drive-train state, not a queued event, so every read returns it.
        return self._scripted_drive_status

    def send_geofence_update(self, exclusion_zone_ids: list[str]) -> None:
        self.geofence_updates_sent.append(exclusion_zone_ids)

    def trigger_ota(self, firmware_path: str) -> None:
        self.ota_triggers.append(firmware_path)
