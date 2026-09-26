# pathfinder-autonomous/pi-mission/papaya_mission/sync_client.py
"""Pushes unsynced local-store records to the backend's /sync/*
endpoints (Backend Obstacle & Telemetry Sync plan). See design spec:
Mission Flow -- Completion & sync.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

import httpx

from papaya_mission import local_store


def sync_sweep_sessions(conn: sqlite3.Connection, client: httpx.Client, base_url: str) -> int:
    unsynced = local_store.list_unsynced_sweep_sessions(conn)
    if not unsynced:
        return 0

    payload = {"sessions": [_sweep_session_to_wire(s) for s in unsynced]}
    response = client.post(f"{base_url}/sync/sweep-sessions", json=payload)
    response.raise_for_status()

    now = datetime.now(timezone.utc)
    local_store.mark_sweep_sessions_synced(conn, [s["id"] for s in unsynced], now)
    return len(unsynced)


def _sweep_session_to_wire(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "_id": session["id"],
        "rover_id": session["rover_id"],
        "geofence_id": session["geofence_id"],
        "status": session["status"],
        "pattern": session["pattern"],
        "last_completed_waypoint_index": session["last_completed_waypoint_index"],
        "started_at": session["started_at"].isoformat(),
        "interrupted_at": (
            session["interrupted_at"].isoformat() if session["interrupted_at"] else None
        ),
        "completed_at": session["completed_at"].isoformat() if session["completed_at"] else None,
    }


def sync_obstacles(conn: sqlite3.Connection, client: httpx.Client, base_url: str) -> int:
    unsynced = local_store.list_unsynced_obstacles(conn)
    if not unsynced:
        return 0

    payload = {"obstacles": [_obstacle_to_wire(o) for o in unsynced]}
    response = client.post(f"{base_url}/sync/obstacles", json=payload)
    response.raise_for_status()

    now = datetime.now(timezone.utc)
    local_store.mark_obstacles_synced(conn, [o["id"] for o in unsynced], now)
    return len(unsynced)


def _obstacle_to_wire(obstacle: dict[str, Any]) -> dict[str, Any]:
    lon, lat = obstacle["position"]
    return {
        "_id": obstacle["id"],
        "sweep_session_id": obstacle["sweep_session_id"],
        "position": {"type": "Point", "coordinates": [lon, lat]},
        "position_uncertainty_m": obstacle["position_uncertainty_m"],
        "type": obstacle["type"],
        "classification_confidence": obstacle["classification_confidence"],
        "detection_method": obstacle["detection_method"],
        "status": obstacle["status"],
        "first_detected_at": obstacle["first_detected_at"].isoformat(),
        "last_confirmed_at": (
            obstacle["last_confirmed_at"].isoformat() if obstacle["last_confirmed_at"] else None
        ),
    }


DEFAULT_TELEMETRY_SYNC_CHUNK_SIZE = 500


def sync_telemetry(
    conn: sqlite3.Connection,
    client: httpx.Client,
    base_url: str,
    chunk_size: int = DEFAULT_TELEMETRY_SYNC_CHUNK_SIZE,
) -> int:
    """Pushes unsynced telemetry, POSTing at most `chunk_size` records
    per request and marking each chunk synced before starting the next.

    Telemetry is the highest-volume entity here (obstacles and sweep
    sessions are rare, high-value events), so a long offline stretch can
    build a backlog large enough to hit a request-size or timeout limit.
    Sent as one request, such a backlog would fail identically on every
    future attempt and never drain. Chunking lets each sync make partial
    progress instead.

    This is separate from the deliberate no-retry/no-backoff decision:
    on a mid-batch failure the already-POSTed chunks stay marked synced
    (they did succeed) and the failing chunk's records stay unsynced for
    the next attempt, exactly as the no-retry contract prescribes.
    """
    unsynced = local_store.list_unsynced_telemetry(conn)
    if not unsynced:
        return 0

    synced_count = 0
    for start in range(0, len(unsynced), chunk_size):
        chunk = unsynced[start : start + chunk_size]
        payload = {"records": [_telemetry_to_wire(r) for r in chunk]}
        response = client.post(f"{base_url}/sync/telemetry", json=payload)
        response.raise_for_status()

        now = datetime.now(timezone.utc)
        local_store.mark_telemetry_synced(conn, [r["id"] for r in chunk], now)
        synced_count += len(chunk)

    return synced_count


def _telemetry_to_wire(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "_id": record["id"],
        "rover_id": record["rover_id"],
        "timestamp": record["timestamp"].isoformat(),
        "local_tz_offset_minutes": record["local_tz_offset_minutes"],
        "sweep_session_id": record["sweep_session_id"],
        "sequence_number": record["sequence_number"],
        "metrics": record["metrics"],
    }


def sync_all(conn: sqlite3.Connection, client: httpx.Client, base_url: str) -> dict[str, int]:
    """Called at a Home-return checkpoint. Order matters: sweep sessions
    and obstacles sync before telemetry, so the backend has the parent
    records in place before telemetry references them by
    sweep_session_id.
    """
    return {
        "sweep_sessions": sync_sweep_sessions(conn, client, base_url),
        "obstacles": sync_obstacles(conn, client, base_url),
        "telemetry": sync_telemetry(conn, client, base_url),
    }
