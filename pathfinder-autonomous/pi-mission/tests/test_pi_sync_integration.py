from datetime import datetime, timezone

import httpx

from papaya_mission import local_store, sync_client
from papaya_mission.telemetry_record import build_telemetry_record

TIMESTAMP = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


def test_generate_store_and_sync_telemetry_end_to_end():
    conn = local_store.connect(":memory:")
    try:
        record = build_telemetry_record(
            record_id="tel-1",
            rover_id="rover-1",
            timestamp=TIMESTAMP,
            local_tz_offset_minutes=-300,
            sequence_number=1,
            readings={"battery_voltage": 11.8},
            expected_metrics={"battery_voltage", "wifi_rssi"},
            sweep_session_id="sess-1",
        )
        assert record["metrics"] == {"battery_voltage": 11.8, "wifi_rssi": "missing"}

        local_store.save_telemetry_record(conn, record)
        local_store.commit(conn)  # telemetry needs an explicit commit
        assert len(local_store.list_unsynced_telemetry(conn)) == 1

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"received": 1, "inserted": 1})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        count = sync_client.sync_telemetry(conn, client, "http://backend.local:8000")

        assert count == 1
        assert local_store.list_unsynced_telemetry(conn) == []
    finally:
        conn.close()
