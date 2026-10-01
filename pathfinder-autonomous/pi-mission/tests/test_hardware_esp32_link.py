import json

from papaya_mission.hardware_esp32_link import HardwareEsp32Link


class _FakeTransport:
    def __init__(self, lines: list[bytes] | None = None):
        self._lines = list(lines or [])
        self.written: list[bytes] = []

    def readline(self) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        return b""

    def write(self, data: bytes) -> None:
        self.written.append(data)


def _line(message: dict) -> bytes:
    return (json.dumps(message) + "\n").encode("utf-8")


def test_poll_bump_events_returns_empty_when_nothing_arrived():
    link = HardwareEsp32Link(transport=_FakeTransport(), port="/dev/fake")

    assert link.poll_bump_events() == []


def test_poll_bump_events_drains_bump_lines_and_consumes_once():
    transport = _FakeTransport([_line({"type": "bump"}), _line({"type": "bump"})])
    link = HardwareEsp32Link(transport=transport, port="/dev/fake")

    events = link.poll_bump_events()
    assert len(events) == 2
    assert link.poll_bump_events() == []


def test_status_reflects_latest_heartbeat_halted_flag():
    transport = _FakeTransport([
        _line({"type": "status", "halted": False, "throttle": 0.0}),
        _line({"type": "status", "halted": True, "throttle": 0.3}),
    ])
    link = HardwareEsp32Link(transport=transport, port="/dev/fake")

    assert link.status().halted_on_contact is True


def test_read_drive_status_reflects_latest_heartbeat_throttle():
    transport = _FakeTransport([_line({"type": "status", "halted": False, "throttle": 0.42})])
    link = HardwareEsp32Link(transport=transport, port="/dev/fake")

    status = link.read_drive_status()
    assert status.servo_positions_deg == {}
    assert status.throttle_position == 0.42


def test_malformed_line_is_skipped_without_raising():
    transport = _FakeTransport([b"not json at all\n", _line({"type": "bump"})])
    link = HardwareEsp32Link(transport=transport, port="/dev/fake")

    events = link.poll_bump_events()
    assert len(events) == 1


def test_non_dict_json_is_skipped_without_raising():
    # JSON that parses but isn't a dict (e.g., a bare number, array, or boolean)
    transport = _FakeTransport([
        b"5\n",
        b"[1, 2, 3]\n",
        b"true\n",
        _line({"type": "bump"}),
    ])
    link = HardwareEsp32Link(transport=transport, port="/dev/fake")

    events = link.poll_bump_events()
    assert len(events) == 1


def test_status_with_non_numeric_throttle_is_skipped_without_raising():
    # Status message with non-numeric throttle should be skipped, but subsequent valid messages should process
    transport = _FakeTransport([
        _line({"type": "status", "halted": False, "throttle": "not-a-number"}),
        _line({"type": "status", "halted": True, "throttle": 0.5}),
    ])
    link = HardwareEsp32Link(transport=transport, port="/dev/fake")

    # First status is skipped, second one should set the values
    status = link.status()
    assert status.halted_on_contact is True
    assert link.read_drive_status().throttle_position == 0.5


def test_unknown_message_type_is_ignored():
    transport = _FakeTransport([_line({"type": "something_unexpected"})])
    link = HardwareEsp32Link(transport=transport, port="/dev/fake")

    assert link.status().halted_on_contact is False
    assert link.poll_bump_events() == []


def test_send_geofence_update_writes_json_line_and_records_call():
    transport = _FakeTransport()
    link = HardwareEsp32Link(transport=transport, port="/dev/fake")

    link.send_geofence_update(["zone-1", "zone-2"])

    assert link.geofence_updates_sent == [["zone-1", "zone-2"]]
    written = json.loads(transport.written[0].decode("utf-8").strip())
    assert written == {"type": "geofence_update", "zone_ids": ["zone-1", "zone-2"]}


def test_trigger_ota_invokes_flash_runner_with_port_and_path_and_records_call():
    calls = []

    def fake_flash_runner(port: str, firmware_path: str) -> bool:
        calls.append((port, firmware_path))
        return True

    link = HardwareEsp32Link(transport=_FakeTransport(), port="/dev/fake", flash_runner=fake_flash_runner)

    link.trigger_ota("/firmware/v2.bin")

    assert link.ota_triggers == ["/firmware/v2.bin"]
    assert calls == [("/dev/fake", "/firmware/v2.bin")]


def test_trigger_ota_logs_error_when_flash_runner_fails(caplog):
    link = HardwareEsp32Link(
        transport=_FakeTransport(), port="/dev/fake", flash_runner=lambda port, path: False
    )

    with caplog.at_level("ERROR"):
        link.trigger_ota("/firmware/v2.bin")

    assert any("flash failed" in record.message for record in caplog.records)
