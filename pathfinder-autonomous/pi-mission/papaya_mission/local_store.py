"""SQLite-backed local store for MP-1's obstacle/sweep-session/telemetry
records. See design spec: Data Model -- Local vs. Mongo storage.

Field names and shapes match the wire format used across the codebase
(e.g. `position` is a (lon, lat) tuple) rather than introducing a new
dataclass hierarchy -- there are already three representations of these
shapes (Pi pure-domain objects, backend Pydantic models, wire JSON); a
fourth isn't worth it for what's fundamentally row storage.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sweep_sessions (
    id TEXT PRIMARY KEY,
    rover_id TEXT NOT NULL,
    geofence_id TEXT NOT NULL,
    status TEXT NOT NULL,
    pattern_json TEXT NOT NULL,
    last_completed_waypoint_index INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    interrupted_at TEXT,
    completed_at TEXT,
    synced_at TEXT
);

CREATE TABLE IF NOT EXISTS obstacles (
    id TEXT PRIMARY KEY,
    sweep_session_id TEXT NOT NULL,
    position_lon REAL NOT NULL,
    position_lat REAL NOT NULL,
    position_uncertainty_m REAL NOT NULL,
    type TEXT NOT NULL,
    classification_confidence REAL NOT NULL,
    detection_method TEXT NOT NULL,
    status TEXT NOT NULL,
    first_detected_at TEXT NOT NULL,
    last_confirmed_at TEXT,
    synced_at TEXT
);

CREATE TABLE IF NOT EXISTS telemetry (
    id TEXT PRIMARY KEY,
    rover_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    local_tz_offset_minutes INTEGER NOT NULL,
    sweep_session_id TEXT,
    sequence_number INTEGER NOT NULL,
    metrics_json TEXT NOT NULL,
    synced_at TEXT
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def commit(conn: sqlite3.Connection) -> None:
    conn.commit()


DEFAULT_TELEMETRY_COMMIT_INTERVAL_S = 60.0


def should_commit_telemetry(
    last_commit_at: datetime | None,
    now: datetime,
    interval_s: float = DEFAULT_TELEMETRY_COMMIT_INTERVAL_S,
) -> bool:
    """Whether enough time has passed since the last telemetry commit to
    flush again. `last_commit_at=None` (nothing committed yet this
    session) always returns True. The interval is a plain parameter
    backed by a named constant, not a number buried in a scheduling
    loop somewhere -- change DEFAULT_TELEMETRY_COMMIT_INTERVAL_S (or
    pass a different `interval_s`) if the SD-card-wear tradeoff ever
    needs revisiting. This function only answers "should I" -- the
    caller (mission runtime) tracks `last_commit_at` and calls
    `commit()` itself when this returns True.
    """
    if last_commit_at is None:
        return True
    return (now - last_commit_at).total_seconds() >= interval_s


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_iso(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


# --- Obstacles ---------------------------------------------------------

def save_obstacle(conn: sqlite3.Connection, obstacle: dict[str, Any]) -> None:
    lon, lat = obstacle["position"]
    conn.execute(
        """
        INSERT INTO obstacles (
            id, sweep_session_id, position_lon, position_lat,
            position_uncertainty_m, type, classification_confidence,
            detection_method, status, first_detected_at, last_confirmed_at,
            synced_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        ON CONFLICT(id) DO UPDATE SET
            position_lon = excluded.position_lon,
            position_lat = excluded.position_lat,
            position_uncertainty_m = excluded.position_uncertainty_m,
            type = excluded.type,
            classification_confidence = excluded.classification_confidence,
            detection_method = excluded.detection_method,
            status = excluded.status,
            last_confirmed_at = excluded.last_confirmed_at,
            synced_at = NULL
        """,
        (
            obstacle["id"],
            obstacle["sweep_session_id"],
            lon,
            lat,
            obstacle["position_uncertainty_m"],
            obstacle["type"],
            obstacle["classification_confidence"],
            obstacle["detection_method"],
            obstacle["status"],
            _iso(obstacle["first_detected_at"]),
            _iso(obstacle.get("last_confirmed_at")),
        ),
    )
    conn.commit()  # immediate -- rare, high-value event


def list_unsynced_obstacles(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM obstacles WHERE synced_at IS NULL").fetchall()
    return [_row_to_obstacle(row) for row in rows]


def mark_obstacles_synced(
    conn: sqlite3.Connection, obstacle_ids: list[str], synced_at: datetime
) -> None:
    conn.executemany(
        "UPDATE obstacles SET synced_at = ? WHERE id = ?",
        [(_iso(synced_at), obstacle_id) for obstacle_id in obstacle_ids],
    )
    conn.commit()


def _row_to_obstacle(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "sweep_session_id": row["sweep_session_id"],
        "position": (row["position_lon"], row["position_lat"]),
        "position_uncertainty_m": row["position_uncertainty_m"],
        "type": row["type"],
        "classification_confidence": row["classification_confidence"],
        "detection_method": row["detection_method"],
        "status": row["status"],
        "first_detected_at": _parse_iso(row["first_detected_at"]),
        "last_confirmed_at": _parse_iso(row["last_confirmed_at"]),
        "synced_at": _parse_iso(row["synced_at"]),
    }


# --- Sweep sessions ------------------------------------------------------

def save_sweep_session(conn: sqlite3.Connection, session: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO sweep_sessions (
            id, rover_id, geofence_id, status, pattern_json,
            last_completed_waypoint_index, started_at, interrupted_at,
            completed_at, synced_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        ON CONFLICT(id) DO UPDATE SET
            status = excluded.status,
            last_completed_waypoint_index = excluded.last_completed_waypoint_index,
            interrupted_at = excluded.interrupted_at,
            completed_at = excluded.completed_at,
            synced_at = NULL
        """,
        (
            session["id"],
            session["rover_id"],
            session["geofence_id"],
            session["status"],
            json.dumps(session["pattern"]),
            session["last_completed_waypoint_index"],
            _iso(session["started_at"]),
            _iso(session.get("interrupted_at")),
            _iso(session.get("completed_at")),
        ),
    )
    conn.commit()  # immediate -- rare, high-value event


def list_unsynced_sweep_sessions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM sweep_sessions WHERE synced_at IS NULL").fetchall()
    return [_row_to_sweep_session(row) for row in rows]


def mark_sweep_sessions_synced(
    conn: sqlite3.Connection, session_ids: list[str], synced_at: datetime
) -> None:
    conn.executemany(
        "UPDATE sweep_sessions SET synced_at = ? WHERE id = ?",
        [(_iso(synced_at), session_id) for session_id in session_ids],
    )
    conn.commit()


def _row_to_sweep_session(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "rover_id": row["rover_id"],
        "geofence_id": row["geofence_id"],
        "status": row["status"],
        "pattern": json.loads(row["pattern_json"]),
        "last_completed_waypoint_index": row["last_completed_waypoint_index"],
        "started_at": _parse_iso(row["started_at"]),
        "interrupted_at": _parse_iso(row["interrupted_at"]),
        "completed_at": _parse_iso(row["completed_at"]),
        "synced_at": _parse_iso(row["synced_at"]),
    }


# --- Telemetry -------------------------------------------------------------

def save_telemetry_record(conn: sqlite3.Connection, record: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO telemetry (
            id, rover_id, timestamp, local_tz_offset_minutes,
            sweep_session_id, sequence_number, metrics_json, synced_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
        ON CONFLICT(id) DO NOTHING
        """,
        (
            record["id"],
            record["rover_id"],
            _iso(record["timestamp"]),
            record["local_tz_offset_minutes"],
            record.get("sweep_session_id"),
            record["sequence_number"],
            json.dumps(record["metrics"]),
        ),
    )
    # Deliberately NOT committed here -- telemetry is high-frequency;
    # caller batches commits on a ~1-minute cadence via commit().


def list_unsynced_telemetry(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM telemetry WHERE synced_at IS NULL ORDER BY sequence_number"
    ).fetchall()
    return [_row_to_telemetry(row) for row in rows]


def mark_telemetry_synced(
    conn: sqlite3.Connection, record_ids: list[str], synced_at: datetime
) -> None:
    conn.executemany(
        "UPDATE telemetry SET synced_at = ? WHERE id = ?",
        [(_iso(synced_at), record_id) for record_id in record_ids],
    )
    conn.commit()


def _row_to_telemetry(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "rover_id": row["rover_id"],
        "timestamp": _parse_iso(row["timestamp"]),
        "local_tz_offset_minutes": row["local_tz_offset_minutes"],
        "sweep_session_id": row["sweep_session_id"],
        "sequence_number": row["sequence_number"],
        "metrics": json.loads(row["metrics_json"]),
        "synced_at": _parse_iso(row["synced_at"]),
    }
