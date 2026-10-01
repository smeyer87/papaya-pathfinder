"""Real Esp32Link implementation over the Pi<->ESP32 UART link -- see
design spec: docs/superpowers/specs/2026-09-30-breadboard-bench-rig-design.md.

Message framing is newline-delimited JSON. The ESP32 pushes a heartbeat
(halted flag + throttle) roughly every 150ms plus an eager bump message
the instant one occurs -- this driver never blocks waiting for a reply,
it just drains whatever has arrived on the transport each time a
Protocol method is called and serves the request from cached state.

The transport and flash-runner are both injected via the constructor so
every line of protocol logic here is testable without a real serial port
or a real ESP32. Constructing the real pyserial-backed transport, and
invoking a real esptool.py flash against real hardware, are bench-time
work -- not built here.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from papaya_mission.esp32_link import BumpEvent, DriveStatus, Esp32Status

logger = logging.getLogger("papaya_mission.hardware_esp32_link")


class HardwareTransport(Protocol):
    """Duck-typed shape of the Pi<->ESP32 serial link this driver needs.
    `readline()` must return b"" (not block) when nothing new has
    arrived yet -- matching pyserial's own non-blocking-timeout mode,
    not its default blocking behavior.
    """

    def readline(self) -> bytes: ...
    def write(self, data: bytes) -> None: ...


class FlashRunner(Protocol):
    """Invokes esptool.py against the given port with the given firmware
    file, returning True on success.
    """

    def __call__(self, port: str, firmware_path: str) -> bool: ...


def _default_flash_runner(port: str, firmware_path: str) -> bool:
    raise NotImplementedError(
        "Real esptool.py flashing is bench-time work -- "
        "inject a flash_runner, or implement this once hardware is on hand."
    )


@dataclass
class HardwareEsp32Link:
    """Real Esp32Link implementation. This driver does not own exclusive
    access to `port` itself (the caller's transport does) -- trigger_ota()
    expects the caller to release/close the transport's hold on the port
    before calling it, and reopen it afterward, since esptool needs the
    port free. See the design spec's OTA section for the full mechanism.
    """

    transport: HardwareTransport
    port: str
    flash_runner: FlashRunner = _default_flash_runner
    _pending_bump_events: list[BumpEvent] = field(default_factory=list)
    _halted_on_contact: bool = False
    _last_throttle: float = 0.0
    geofence_updates_sent: list[list[str]] = field(default_factory=list)
    ota_triggers: list[str] = field(default_factory=list)

    def _drain_transport(self) -> None:
        while True:
            line = self.transport.readline()
            if not line:
                break
            self._handle_line(line)

    def _handle_line(self, line: bytes) -> None:
        try:
            message = json.loads(line.decode("utf-8").strip())
        except (ValueError, UnicodeDecodeError):
            logger.warning("Malformed line from ESP32: %r", line, exc_info=True)
            return
        if not isinstance(message, dict):
            logger.warning("Expected JSON object, got %r", message)
            return
        try:
            message_type = message.get("type")
            if message_type == "bump":
                self._pending_bump_events.append(BumpEvent(detected_at=datetime.now(timezone.utc)))
            elif message_type == "status":
                self._halted_on_contact = bool(message.get("halted", False))
                self._last_throttle = float(message.get("throttle", 0.0))
            else:
                logger.warning("Unknown message type from ESP32: %r", message_type)
        except (ValueError, TypeError) as e:
            logger.warning("Error processing message from ESP32: %r: %s", message, e)

    def poll_bump_events(self) -> list[BumpEvent]:
        self._drain_transport()
        events, self._pending_bump_events = self._pending_bump_events, []
        return events

    def status(self) -> Esp32Status:
        self._drain_transport()
        return Esp32Status(halted_on_contact=self._halted_on_contact)

    def read_drive_status(self) -> DriveStatus:
        self._drain_transport()
        return DriveStatus(servo_positions_deg={}, throttle_position=self._last_throttle)

    def send_geofence_update(self, exclusion_zone_ids: list[str]) -> None:
        self.geofence_updates_sent.append(exclusion_zone_ids)
        line = json.dumps({"type": "geofence_update", "zone_ids": exclusion_zone_ids}) + "\n"
        self.transport.write(line.encode("utf-8"))

    def trigger_ota(self, firmware_path: str) -> None:
        self.ota_triggers.append(firmware_path)
        success = self.flash_runner(self.port, firmware_path)
        if not success:
            logger.error("esptool flash failed for %s on %s", firmware_path, self.port)
