# pathfinder-autonomous/pi-mission/tests/test_sync_client.py
import json
from datetime import datetime, timezone

import httpx
import pytest

from papaya_mission import local_store, sync_client

DETECTED_AT = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
DETECTED_AT_ISO = "2026-09-24T12:00:00+00:00"
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


def _sweep_session(session_id="sess-1"):
    return {
        "id": session_id,
        "rover_id": "rover-1",
        "geofence_id": "fence-1",
        "status": "completed",
        "pattern": [
            {
                "order": 0,
                "position": {"type": "Point", "coordinates": [-85.0, 38.0]},
                "leg_index": 0,
            },
            {
                "order": 1,
                "position": {"type": "Point", "coordinates": [-85.001, 38.001]},
                "leg_index": 1,
            },
        ],
        "last_completed_waypoint_index": 1,
        "started_at": DETECTED_AT,
        "interrupted_at": None,
        "completed_at": DETECTED_AT,
    }


def _telemetry_record(record_id="tel-1", sequence_number=1):
    return {
        "id": record_id,
        "rover_id": "rover-1",
        "timestamp": DETECTED_AT,
        "local_tz_offset_minutes": -300,
        "sweep_session_id": "sess-1",
        "sequence_number": sequence_number,
        "metrics": {"battery_voltage": 11.8},
    }


def _body_capturing_client(bodies: list[dict], paths: list[str] | None = None) -> httpx.Client:
    """A MockTransport client that records the actual JSON body of every
    request. Asserting on the body (not just the URL) is the whole point
    of these tests -- the wire shape is the seam between the Pi and the
    backend's /sync/* Pydantic models, and a malformed payload would
    otherwise pass every URL-only assertion silently.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        if paths is not None:
            paths.append(request.url.path)
        return httpx.Response(200, json={"received": 1, "inserted": 1})

    return httpx.Client(transport=httpx.MockTransport(handler))


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


# --- Wire payload bodies ---------------------------------------------------
#
# These assert the exact JSON that goes on the wire, field for field.
# The /sync/* endpoints parse it with Pydantic models that use `_id`
# aliases and GeoJSON Point positions, so a drift in `_obstacle_to_wire`
# and friends is a real integration break that URL-only assertions can't
# catch.

def test_sync_obstacles_sends_the_expected_wire_body(conn):
    local_store.save_obstacle(conn, _obstacle())
    bodies: list[dict] = []
    client = _body_capturing_client(bodies)

    sync_client.sync_obstacles(conn, client, BASE_URL)

    assert len(bodies) == 1
    assert bodies[0] == {
        "obstacles": [
            {
                "_id": "obs-1",
                "sweep_session_id": "sess-1",
                "position": {"type": "Point", "coordinates": [-85.0005, 38.0005]},
                "position_uncertainty_m": 1.5,
                "type": "barrel",
                "classification_confidence": 0.9,
                "detection_method": "ultrasonic+camera",
                "status": "permanent-pending",
                "first_detected_at": DETECTED_AT_ISO,
                "last_confirmed_at": None,
            }
        ]
    }


def test_sync_sweep_sessions_sends_the_expected_wire_body(conn):
    local_store.save_sweep_session(conn, _sweep_session())
    bodies: list[dict] = []
    client = _body_capturing_client(bodies)

    sync_client.sync_sweep_sessions(conn, client, BASE_URL)

    assert len(bodies) == 1
    assert bodies[0] == {
        "sessions": [
            {
                "_id": "sess-1",
                "rover_id": "rover-1",
                "geofence_id": "fence-1",
                "status": "completed",
                "pattern": [
                    {
                        "order": 0,
                        "position": {"type": "Point", "coordinates": [-85.0, 38.0]},
                        "leg_index": 0,
                    },
                    {
                        "order": 1,
                        "position": {"type": "Point", "coordinates": [-85.001, 38.001]},
                        "leg_index": 1,
                    },
                ],
                "last_completed_waypoint_index": 1,
                "started_at": DETECTED_AT_ISO,
                "interrupted_at": None,
                "completed_at": DETECTED_AT_ISO,
            }
        ]
    }


def test_sync_telemetry_sends_the_expected_wire_body(conn):
    local_store.save_telemetry_record(conn, _telemetry_record())
    local_store.commit(conn)
    bodies: list[dict] = []
    client = _body_capturing_client(bodies)

    sync_client.sync_telemetry(conn, client, BASE_URL)

    assert len(bodies) == 1
    assert bodies[0] == {
        "records": [
            {
                "_id": "tel-1",
                "rover_id": "rover-1",
                "timestamp": DETECTED_AT_ISO,
                "local_tz_offset_minutes": -300,
                "sweep_session_id": "sess-1",
                "sequence_number": 1,
                "metrics": {"battery_voltage": 11.8},
            }
        ]
    }


# --- Telemetry batch chunking ----------------------------------------------
#
# Telemetry is the highest-volume entity, so a long offline stretch can
# build a backlog big enough to blow a request-size or timeout limit. An
# unchunked POST would then fail identically on every future attempt,
# with no way to make partial progress. Chunking is orthogonal to the
# deliberate no-retry/no-backoff decision: that's about *when* to retry,
# this is about how much to send per request.

def test_sync_telemetry_splits_a_backlog_into_multiple_chunked_requests(conn):
    for index in range(3):
        local_store.save_telemetry_record(
            conn, _telemetry_record(f"tel-{index}", sequence_number=index)
        )
    local_store.commit(conn)
    bodies: list[dict] = []
    client = _body_capturing_client(bodies)

    count = sync_client.sync_telemetry(conn, client, BASE_URL, chunk_size=2)

    assert count == 3
    assert len(bodies) == 2
    assert [r["_id"] for r in bodies[0]["records"]] == ["tel-0", "tel-1"]
    assert [r["_id"] for r in bodies[1]["records"]] == ["tel-2"]
    assert local_store.list_unsynced_telemetry(conn) == []


def test_sync_telemetry_keeps_earlier_chunks_synced_when_a_later_chunk_fails(conn):
    for index in range(3):
        local_store.save_telemetry_record(
            conn, _telemetry_record(f"tel-{index}", sequence_number=index)
        )
    local_store.commit(conn)
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(200, json={"received": 2, "inserted": 2})
        return httpx.Response(500, json={"detail": "internal error"})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(httpx.HTTPStatusError):
        sync_client.sync_telemetry(conn, client, BASE_URL, chunk_size=2)

    # The first chunk genuinely succeeded, so it stays synced; only the
    # failed chunk is left for the next attempt. That's the partial
    # progress an unchunked sync could never make.
    still_unsynced = local_store.list_unsynced_telemetry(conn)
    assert [r["id"] for r in still_unsynced] == ["tel-2"]


def test_sync_telemetry_sends_one_request_when_the_backlog_fits_a_single_chunk(conn):
    local_store.save_telemetry_record(conn, _telemetry_record())
    local_store.commit(conn)
    bodies: list[dict] = []
    client = _body_capturing_client(bodies)

    count = sync_client.sync_telemetry(conn, client, BASE_URL)

    assert count == 1
    assert len(bodies) == 1


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
