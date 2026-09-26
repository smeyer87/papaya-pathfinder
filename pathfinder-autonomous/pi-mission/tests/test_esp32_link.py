from datetime import datetime, timezone

from papaya_mission.esp32_link import BumpEvent, DriveStatus, Esp32Status, FakeEsp32Link


def test_poll_bump_events_returns_empty_by_default():
    link = FakeEsp32Link()

    assert link.poll_bump_events() == []


def test_poll_bump_events_returns_scripted_events_once():
    link = FakeEsp32Link()
    event = BumpEvent(detected_at=datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc))
    link.script_bump_events([event])

    assert link.poll_bump_events() == [event]
    assert link.poll_bump_events() == []


def test_status_defaults_to_not_halted():
    link = FakeEsp32Link()

    assert link.status() == Esp32Status(halted_on_contact=False)


def test_status_returns_scripted_value():
    link = FakeEsp32Link()
    link.script_status(Esp32Status(halted_on_contact=True))

    assert link.status() == Esp32Status(halted_on_contact=True)


def test_read_drive_status_defaults_to_neutral_with_no_servos():
    link = FakeEsp32Link()

    assert link.read_drive_status() == DriveStatus(
        servo_positions_deg={}, throttle_position=0.0
    )


def test_read_drive_status_returns_scripted_value_repeatedly():
    """Unlike poll_bump_events, drive status is current state rather than a
    queued event, so it is NOT consume-once -- every read returns it.
    """
    link = FakeEsp32Link()
    status = DriveStatus(servo_positions_deg={"fl": 12.5, "fr": -8.0}, throttle_position=0.3)
    link.script_drive_status(status)

    assert link.read_drive_status() == status
    assert link.read_drive_status() == status


def test_send_geofence_update_and_trigger_ota_are_recorded():
    link = FakeEsp32Link()

    link.send_geofence_update(["zone-1", "zone-2"])
    link.trigger_ota("/firmware/v2.bin")

    assert link.geofence_updates_sent == [["zone-1", "zone-2"]]
    assert link.ota_triggers == ["/firmware/v2.bin"]
