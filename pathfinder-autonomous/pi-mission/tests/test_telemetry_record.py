from datetime import datetime, timezone

from papaya_mission.telemetry_record import build_telemetry_record

TIMESTAMP = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


def test_present_metric_keeps_its_value():
    record = build_telemetry_record(
        record_id="tel-1",
        rover_id="rover-1",
        timestamp=TIMESTAMP,
        local_tz_offset_minutes=-300,
        sequence_number=1,
        readings={"battery_voltage": 11.8},
        expected_metrics={"battery_voltage"},
    )

    assert record["metrics"]["battery_voltage"] == 11.8


def test_expected_but_missing_metric_gets_sentinel():
    record = build_telemetry_record(
        record_id="tel-1",
        rover_id="rover-1",
        timestamp=TIMESTAMP,
        local_tz_offset_minutes=-300,
        sequence_number=1,
        readings={},
        expected_metrics={"battery_voltage"},
    )

    assert record["metrics"]["battery_voltage"] == "missing"


def test_not_applicable_metric_is_omitted_even_if_a_reading_exists():
    record = build_telemetry_record(
        record_id="tel-1",
        rover_id="rover-1",
        timestamp=TIMESTAMP,
        local_tz_offset_minutes=-300,
        sequence_number=1,
        readings={"battery_voltage": 11.8, "cell_voltage_1": 3.9},  # not on this rover's manifest
        expected_metrics={"battery_voltage"},
    )

    assert "cell_voltage_1" not in record["metrics"]
    assert record["metrics"] == {"battery_voltage": 11.8}


def test_grouped_array_values_pass_through_unmodified():
    record = build_telemetry_record(
        record_id="tel-1",
        rover_id="rover-1",
        timestamp=TIMESTAMP,
        local_tz_offset_minutes=-300,
        sequence_number=1,
        readings={"motors": [{"id": 1, "current": 0.8}, {"id": 2, "current": 0.9}]},
        expected_metrics={"motors"},
    )

    assert record["metrics"]["motors"] == [{"id": 1, "current": 0.8}, {"id": 2, "current": 0.9}]


def test_envelope_fields_are_set_correctly():
    record = build_telemetry_record(
        record_id="tel-1",
        rover_id="rover-1",
        timestamp=TIMESTAMP,
        local_tz_offset_minutes=-300,
        sequence_number=7,
        readings={},
        expected_metrics=set(),
        sweep_session_id="sess-1",
    )

    assert record["id"] == "tel-1"
    assert record["rover_id"] == "rover-1"
    assert record["timestamp"] == TIMESTAMP
    assert record["sweep_session_id"] == "sess-1"
    assert record["sequence_number"] == 7
