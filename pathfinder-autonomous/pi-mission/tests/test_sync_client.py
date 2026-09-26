# pathfinder-autonomous/pi-mission/tests/test_sync_client.py
from datetime import datetime, timezone

import httpx
import pytest

from papaya_mission import local_store, sync_client

DETECTED_AT = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
BASE_URL = "http://backend.local:8000"


@pytest.fixture
def conn():
    connection = local_store.connect(":memory:")
    yield connection
    connection.close()


def _obstacle(obstacle_id="obs-1"):
    return {
        "id": obstacle_id,
        "sweep_session_id": "sess-1",
        "position": (-85.0005, 38.0005),
        "position_uncertainty_m": 1.5,
        "type": "barrel",
        "classification_confidence": 0.9,
        "detection_method": "ultrasonic+camera",
        "status": "permanent-pending",
        "first_detected_at": DETECTED_AT,
        "last_confirmed_at": None,
    }


def test_sync_obstacles_pushes_unsynced_records_and_marks_them_synced(conn):
    local_store.save_obstacle(conn, _obstacle())
    requests_made = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_made.append(request)
        return httpx.Response(200, json={"received": 1, "inserted": 1})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    count = sync_client.sync_obstacles(conn, client, BASE_URL)

    assert count == 1
    assert len(requests_made) == 1
    assert requests_made[0].url == f"{BASE_URL}/sync/obstacles"
    assert local_store.list_unsynced_obstacles(conn) == []


def test_sync_obstacles_with_nothing_unsynced_makes_no_request(conn):
    requests_made = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_made.append(request)
        return httpx.Response(200, json={"received": 0, "inserted": 0})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    count = sync_client.sync_obstacles(conn, client, BASE_URL)

    assert count == 0
    assert requests_made == []


def test_sync_obstacles_leaves_records_unsynced_on_server_error(conn):
    local_store.save_obstacle(conn, _obstacle())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "internal error"})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(httpx.HTTPStatusError):
        sync_client.sync_obstacles(conn, client, BASE_URL)

    # Not marked synced -- next sync attempt will retry it.
    assert len(local_store.list_unsynced_obstacles(conn)) == 1


def test_sync_all_calls_sweep_sessions_and_obstacles_before_telemetry(conn):
    local_store.save_sweep_session(
        conn,
        {
            "id": "sess-1",
            "rover_id": "rover-1",
            "geofence_id": "fence-1",
            "status": "completed",
            "pattern": [
                {"order": 0, "position": {"type": "Point", "coordinates": [-85.0, 38.0]}}
            ],
            "last_completed_waypoint_index": 0,
            "started_at": DETECTED_AT,
            "interrupted_at": None,
            "completed_at": DETECTED_AT,
        },
    )
    local_store.save_obstacle(conn, _obstacle())
    local_store.save_telemetry_record(
        conn,
        {
            "id": "tel-1",
            "rover_id": "rover-1",
            "timestamp": DETECTED_AT,
            "local_tz_offset_minutes": -300,
            "sweep_session_id": "sess-1",
            "sequence_number": 1,
            "metrics": {"battery_voltage": 11.8},
        },
    )
    local_store.commit(conn)  # telemetry needs an explicit commit before it's queryable elsewhere
    call_order = []

    def handler(request: httpx.Request) -> httpx.Response:
        call_order.append(request.url.path)
        return httpx.Response(200, json={"received": 1, "inserted": 1})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    counts = sync_client.sync_all(conn, client, BASE_URL)

    assert counts == {"sweep_sessions": 1, "obstacles": 1, "telemetry": 1}
    assert call_order == ["/sync/sweep-sessions", "/sync/obstacles", "/sync/telemetry"]
