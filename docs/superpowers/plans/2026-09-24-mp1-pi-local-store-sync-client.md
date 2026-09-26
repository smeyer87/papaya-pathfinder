# MP-1 Pi Local Store & Sync Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Pi-side half of sync: a local SQLite store (survives a power loss with bounded rework), the two-tier telemetry record builder with missing-value semantics, and a sync client that pushes unsynced records to the backend's `/sync/*` endpoints (Backend Obstacle & Telemetry Sync plan) at a Home-return checkpoint.

**Architecture:** Three modules in `papaya_mission`. `local_store.py` uses Python's built-in `sqlite3` — no server, no Mongo, nothing external. `telemetry_record.py` is pure logic. `sync_client.py` uses `httpx` to talk to the backend, and its tests run against `httpx.MockTransport` (a fake in-process transport) rather than a live server — this plan is fully buildable and testable without MongoDB Atlas or a running backend process. A real end-to-end check against the actual backend is a separate smoke test for once Atlas exists, not something baked into this plan's test suite.

**Tech Stack:** Python 3.11, `sqlite3` (stdlib), `httpx` (new dependency, for the sync client), pytest.

## Global Constraints

- Extends `pathfinder-autonomous/pi-mission/` — same package as the three prior Pi-mission plans.
- **Commit cadence** (2026-09-24 decision): `save_obstacle`/`save_sweep_session` commit immediately — these are rare, high-value events (a detection, a state transition) where losing one to a sudden power loss is costly, and the write volume is far too low to threaten microSD write endurance. `save_telemetry_record` deliberately does **not** auto-commit — telemetry is high-frequency (spec: ~1s while driving, ~5s while idle), and committing every sample would wear the card faster for no real benefit. The interval itself is a named, importable constant (`local_store.DEFAULT_TELEMETRY_COMMIT_INTERVAL_S`, currently `60.0`) rather than a number buried in prose or hardcoded somewhere downstream — easy to change in one place if the tradeoff ever needs revisiting. The caller (mission runtime) tracks `last_commit_at` and asks `local_store.should_commit_telemetry(last_commit_at, now)` on each tick, calling `commit()` when it returns `True`. Mark-synced operations (all three entities) commit immediately too — they're infrequent and checkpoint-triggered, not the high-frequency case this tradeoff is about.
- **Local upsert semantics**: obstacle/sweep-session saves upsert by `id` and reset `synced_at` to `NULL` on update — a locally-modified record (e.g. resume-validation bumping `last_confirmed_at`, or a sweep session transitioning status) must get re-synced, not silently stay marked as already-synced from before the change. Telemetry saves are insert-only (`ON CONFLICT DO NOTHING`) — matches the backend's append-only telemetry semantics from the Backend Obstacle & Telemetry Sync plan.
- **Missing-value tagging**: `expected_metrics` is both floor and ceiling for `build_telemetry_record`'s output — every key in it appears (present or `"missing"`), and anything in the raw readings *outside* that set is silently dropped, not passed through. Matches the design spec: "nothing is written for metrics outside the current sensor configuration."
- The sensor manifest itself (which metrics are "expected" for this rover+mission) is **not fetched from the backend by this plan** — `expected_metrics` is a parameter the caller supplies, having cached it locally for offline operation (same pattern as the already-established local geofence cache). Fetching and caching that manifest is a Mission Runtime concern.
- No retry/backoff policy lives in `sync_client.py` — a failed sync raises (`httpx.HTTPStatusError` or a connection error) and leaves the affected records unsynced for the next attempt. Deciding *when* to retry is a Mission Runtime concern, not this plan's.

---

## File Structure

```
pathfinder-autonomous/
  pi-mission/
    requirements.txt          # MODIFIED -- add httpx
    papaya_mission/
      local_store.py            # NEW -- SQLite schema + save/list-unsynced/mark-synced
      telemetry_record.py         # NEW -- build_telemetry_record()
      sync_client.py                # NEW -- sync_{obstacles,sweep_sessions,telemetry,all}()
    tests/
      test_local_store.py            # NEW
      test_telemetry_record.py         # NEW
      test_sync_client.py                # NEW
      test_pi_sync_integration.py          # NEW
```

---

### Task 1: Local SQLite store

**Files:**
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/local_store.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_local_store.py`

**Interfaces:**
- Produces: `papaya_mission.local_store.connect(db_path: str) -> sqlite3.Connection` (creates the schema if absent; pass `":memory:"` for tests). Per-entity functions: `save_obstacle(conn, obstacle: dict) -> None`, `list_unsynced_obstacles(conn) -> list[dict]`, `mark_obstacles_synced(conn, ids: list[str], synced_at: datetime) -> None`; the same three-function shape for `*_sweep_session(s)` and `*_telemetry`/`*_telemetry_record`. Plus `commit(conn) -> None`, `DEFAULT_TELEMETRY_COMMIT_INTERVAL_S: float` (a named, importable constant — currently `60.0`), and `should_commit_telemetry(last_commit_at: datetime | None, now: datetime, interval_s: float = DEFAULT_TELEMETRY_COMMIT_INTERVAL_S) -> bool`. The mission-runtime plan tracks `last_commit_at` itself and calls `should_commit_telemetry` on each tick to decide whether to call `commit()` — the interval lives in exactly one place, easy to change without hunting through a scheduling loop for a hardcoded number. Records use plain `dict`s with the same field names/shapes as the backend's wire format (e.g. `obstacle["position"]` is a `(lon, lat)` tuple, matching `papaya_mission.obstacle.Obstacle` from the Obstacle Detection & Classification plan) — no new dataclass hierarchy, to avoid a fourth parallel representation of the same shape (Pi pure-domain object, backend Pydantic model, wire JSON, local-store dict).

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_local_store.py
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from papaya_mission import local_store

DETECTED_AT = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def conn():
    connection = local_store.connect(":memory:")
    yield connection
    connection.close()


def _obstacle(obstacle_id="obs-1", status="permanent-pending"):
    return {
        "id": obstacle_id,
        "sweep_session_id": "sess-1",
        "position": (-85.0005, 38.0005),
        "position_uncertainty_m": 1.5,
        "type": "barrel",
        "classification_confidence": 0.9,
        "detection_method": "ultrasonic+camera",
        "status": status,
        "first_detected_at": DETECTED_AT,
        "last_confirmed_at": None,
    }


def _sweep_session(session_id="sess-1", status="in_progress"):
    return {
        "id": session_id,
        "rover_id": "rover-1",
        "geofence_id": "fence-1",
        "status": status,
        "pattern": [{"order": 0, "position": {"type": "Point", "coordinates": [-85.0, 38.0]}}],
        "last_completed_waypoint_index": -1,
        "started_at": DETECTED_AT,
        "interrupted_at": None,
        "completed_at": None,
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


# --- Obstacles ---------------------------------------------------------

def test_save_and_list_unsynced_obstacle(conn):
    local_store.save_obstacle(conn, _obstacle())

    unsynced = local_store.list_unsynced_obstacles(conn)

    assert len(unsynced) == 1
    assert unsynced[0]["id"] == "obs-1"
    assert unsynced[0]["position"] == (-85.0005, 38.0005)
    assert unsynced[0]["first_detected_at"] == DETECTED_AT


def test_mark_obstacles_synced_excludes_them_from_unsynced_list(conn):
    local_store.save_obstacle(conn, _obstacle())

    local_store.mark_obstacles_synced(
        conn, ["obs-1"], datetime(2026, 9, 24, 13, 0, 0, tzinfo=timezone.utc)
    )

    assert local_store.list_unsynced_obstacles(conn) == []


def test_updating_a_synced_obstacle_marks_it_unsynced_again(conn):
    local_store.save_obstacle(conn, _obstacle())
    local_store.mark_obstacles_synced(
        conn, ["obs-1"], datetime(2026, 9, 24, 13, 0, 0, tzinfo=timezone.utc)
    )
    assert local_store.list_unsynced_obstacles(conn) == []

    local_store.save_obstacle(conn, _obstacle(status="permanent-confirmed"))

    unsynced = local_store.list_unsynced_obstacles(conn)
    assert len(unsynced) == 1
    assert unsynced[0]["status"] == "permanent-confirmed"


# --- Sweep sessions ------------------------------------------------------

def test_save_and_list_unsynced_sweep_session(conn):
    local_store.save_sweep_session(conn, _sweep_session())

    unsynced = local_store.list_unsynced_sweep_sessions(conn)

    assert len(unsynced) == 1
    assert unsynced[0]["id"] == "sess-1"
    assert unsynced[0]["pattern"][0]["order"] == 0


def test_updating_a_synced_sweep_session_marks_it_unsynced_again(conn):
    local_store.save_sweep_session(conn, _sweep_session())
    local_store.mark_sweep_sessions_synced(
        conn, ["sess-1"], datetime(2026, 9, 24, 13, 0, 0, tzinfo=timezone.utc)
    )
    assert local_store.list_unsynced_sweep_sessions(conn) == []

    local_store.save_sweep_session(conn, _sweep_session(status="completed"))

    unsynced = local_store.list_unsynced_sweep_sessions(conn)
    assert len(unsynced) == 1
    assert unsynced[0]["status"] == "completed"


# --- Telemetry -------------------------------------------------------------

def test_save_and_list_unsynced_telemetry(conn):
    local_store.save_telemetry_record(conn, _telemetry_record())

    unsynced = local_store.list_unsynced_telemetry(conn)

    assert len(unsynced) == 1
    assert unsynced[0]["metrics"]["battery_voltage"] == 11.8


def test_mark_telemetry_synced_excludes_it_from_unsynced_list(conn):
    local_store.save_telemetry_record(conn, _telemetry_record())

    local_store.mark_telemetry_synced(
        conn, ["tel-1"], datetime(2026, 9, 24, 13, 0, 0, tzinfo=timezone.utc)
    )

    assert local_store.list_unsynced_telemetry(conn) == []


def test_saving_the_same_telemetry_record_twice_is_a_no_op(conn):
    local_store.save_telemetry_record(conn, _telemetry_record())
    local_store.save_telemetry_record(conn, _telemetry_record())  # e.g. a retry

    unsynced = local_store.list_unsynced_telemetry(conn)
    assert len(unsynced) == 1


def test_telemetry_writes_are_not_durable_until_explicit_commit():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test.db")
        writer_conn = local_store.connect(db_path)
        try:
            local_store.save_telemetry_record(writer_conn, _telemetry_record())

            # A second connection to the same file shouldn't see the
            # uncommitted write yet -- proves save_telemetry_record
            # really doesn't auto-commit.
            reader_conn = local_store.connect(db_path)
            try:
                assert local_store.list_unsynced_telemetry(reader_conn) == []
            finally:
                reader_conn.close()

            local_store.commit(writer_conn)

            reader_conn = local_store.connect(db_path)
            try:
                assert len(local_store.list_unsynced_telemetry(reader_conn)) == 1
            finally:
                reader_conn.close()
        finally:
            writer_conn.close()


# --- Commit-interval helper (configurable, not hardcoded) ------------------

def test_should_commit_telemetry_true_when_nothing_committed_yet():
    assert local_store.should_commit_telemetry(last_commit_at=None, now=DETECTED_AT) is True


def test_should_commit_telemetry_false_before_interval_elapses():
    result = local_store.should_commit_telemetry(
        last_commit_at=DETECTED_AT, now=DETECTED_AT, interval_s=60.0
    )

    assert result is False


def test_should_commit_telemetry_true_once_interval_elapses():
    now = DETECTED_AT + timedelta(seconds=61)

    result = local_store.should_commit_telemetry(
        last_commit_at=DETECTED_AT, now=now, interval_s=60.0
    )

    assert result is True


def test_should_commit_telemetry_uses_the_configurable_default_interval():
    just_before_default = DETECTED_AT + timedelta(
        seconds=local_store.DEFAULT_TELEMETRY_COMMIT_INTERVAL_S - 1
    )

    result = local_store.should_commit_telemetry(DETECTED_AT, just_before_default)

    assert result is False
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_local_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'papaya_mission.local_store'`

- [ ] **Step 3: Write the implementation**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/local_store.py
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
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_local_store.py -v`
Expected: PASS (14 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/local_store.py pathfinder-autonomous/pi-mission/tests/test_local_store.py
git commit -m "feat(pi-mission): add SQLite local store with a configurable telemetry commit interval"
```

---

### Task 2: Telemetry record builder

**Files:**
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/telemetry_record.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_telemetry_record.py`

**Interfaces:**
- Produces: `papaya_mission.telemetry_record.build_telemetry_record(record_id: str, rover_id: str, timestamp: datetime, local_tz_offset_minutes: int, sequence_number: int, readings: dict[str, Any], expected_metrics: set[str], sweep_session_id: str | None = None) -> dict[str, Any]`. Output shape matches what `local_store.save_telemetry_record` expects directly. The mission-runtime plan calls this once per sample, supplying `readings` from whatever sensors it polled and `expected_metrics` from the locally-cached sensor manifest.

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/pi-mission/tests/test_telemetry_record.py
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
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_telemetry_record.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'papaya_mission.telemetry_record'`

- [ ] **Step 3: Write the implementation**

```python
# pathfinder-autonomous/pi-mission/papaya_mission/telemetry_record.py
"""Builds a telemetry record with the design spec's three-state metric
semantics. See design spec: Telemetry -- Expected metrics & missing-
value semantics.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def build_telemetry_record(
    record_id: str,
    rover_id: str,
    timestamp: datetime,
    local_tz_offset_minutes: int,
    sequence_number: int,
    readings: dict[str, Any],
    expected_metrics: set[str],
    sweep_session_id: str | None = None,
) -> dict[str, Any]:
    """`expected_metrics` is both floor and ceiling: every key in it
    appears in the output metrics map, either with its real value (if
    present in `readings`) or the "missing" sentinel (if not). Anything
    in `readings` outside `expected_metrics` is silently dropped --
    nothing is written for metrics outside the current sensor
    configuration, even if a stray reading happens to exist for it.
    """
    metrics = {key: readings.get(key, "missing") for key in expected_metrics}

    return {
        "id": record_id,
        "rover_id": rover_id,
        "timestamp": timestamp,
        "local_tz_offset_minutes": local_tz_offset_minutes,
        "sweep_session_id": sweep_session_id,
        "sequence_number": sequence_number,
        "metrics": metrics,
    }
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_telemetry_record.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/telemetry_record.py pathfinder-autonomous/pi-mission/tests/test_telemetry_record.py
git commit -m "feat(pi-mission): add telemetry record builder with missing-value tagging"
```

---

### Task 3: Sync client

**Files:**
- Modify: `pathfinder-autonomous/pi-mission/requirements.txt` (add `httpx`)
- Create: `pathfinder-autonomous/pi-mission/papaya_mission/sync_client.py`
- Test: `pathfinder-autonomous/pi-mission/tests/test_sync_client.py`

**Interfaces:**
- Consumes: `local_store` functions (Task 1).
- Produces: `papaya_mission.sync_client.{sync_obstacles(conn, client: httpx.Client, base_url: str) -> int, sync_sweep_sessions(...) -> int, sync_telemetry(...) -> int, sync_all(conn, client, base_url) -> dict[str, int]}`. Each `sync_*` function pushes everything currently unsynced for that entity to the matching Backend Obstacle & Telemetry Sync plan endpoint, marks them synced on a successful response, and leaves them unsynced (propagating the exception) on failure. `sync_all` calls sweep sessions and obstacles before telemetry, so the backend has parent records before telemetry references them by `sweep_session_id`. The mission-runtime plan calls `sync_all` at each Home-return checkpoint.

- [ ] **Step 1: Add `httpx` to `requirements.txt`**

```
shapely==2.0.6
pytest==8.3.3
httpx==0.27.2
```

Run: `pip install -r requirements.txt`

- [ ] **Step 2: Write the failing tests**

```python
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
```

- [ ] **Step 3: Run the tests and verify they fail**

Run: `pytest tests/test_sync_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'papaya_mission.sync_client'`

- [ ] **Step 4: Write the implementation**

```python
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


def sync_telemetry(conn: sqlite3.Connection, client: httpx.Client, base_url: str) -> int:
    unsynced = local_store.list_unsynced_telemetry(conn)
    if not unsynced:
        return 0

    payload = {"records": [_telemetry_to_wire(r) for r in unsynced]}
    response = client.post(f"{base_url}/sync/telemetry", json=payload)
    response.raise_for_status()

    now = datetime.now(timezone.utc)
    local_store.mark_telemetry_synced(conn, [r["id"] for r in unsynced], now)
    return len(unsynced)


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
```

- [ ] **Step 5: Run the tests and verify they pass**

Run: `pytest tests/test_sync_client.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add pathfinder-autonomous/pi-mission/requirements.txt pathfinder-autonomous/pi-mission/papaya_mission/sync_client.py pathfinder-autonomous/pi-mission/tests/test_sync_client.py
git commit -m "feat(pi-mission): add sync client with mocked-transport tests, no live backend needed"
```

---

### Task 4: Integration test and README update

**Files:**
- Create: `pathfinder-autonomous/pi-mission/tests/test_pi_sync_integration.py`
- Modify: `pathfinder-autonomous/pi-mission/README.md`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: nothing new — proves telemetry generation, local storage, and sync compose correctly end to end.

- [ ] **Step 1: Write the integration test**

```python
# pathfinder-autonomous/pi-mission/tests/test_pi_sync_integration.py
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
```

- [ ] **Step 2: Run it and verify it passes**

Run: `pytest tests/test_pi_sync_integration.py -v`
Expected: PASS

- [ ] **Step 3: Update the README**

Add to the "Modules" list:

```markdown
- `local_store.py` — SQLite local store for obstacles/sweep-sessions/
  telemetry. Obstacle/session saves commit immediately; telemetry saves
  defer commit to the caller (`commit()`), batched per
  `DEFAULT_TELEMETRY_COMMIT_INTERVAL_S` (currently 60s — change this one
  constant, or pass a different `interval_s` to `should_commit_telemetry`,
  if the SD-card-wear tradeoff ever needs revisiting; see the design
  spec's resolved open items).
- `telemetry_record.py` — `build_telemetry_record()`: the two-tier
  telemetry record's missing-value tagging (present / `"missing"` /
  omitted).
- `sync_client.py` — pushes unsynced local-store records to the
  backend's `/sync/*` endpoints at a Home-return checkpoint. Tests run
  against `httpx.MockTransport`, not a live server -- no MongoDB or
  running backend needed to build or test this module.
```

- [ ] **Step 4: Commit**

```bash
git add pathfinder-autonomous/pi-mission
git commit -m "test(pi-mission): add Pi sync integration test, update README"
```

---

## Self-Review Notes

- **Spec coverage:** Local SQLite store as the working copy during a mission (Data Model — Local vs. Mongo storage) ✓ Task 1. Upsert-with-synced-at-reset for mutable records, insert-only for telemetry — mirrors the backend's sync semantics exactly (Backend Obstacle & Telemetry Sync plan) ✓ Task 1. Two-tier telemetry's missing-value/expected-metrics semantics (Telemetry — Expected metrics & missing-value semantics) ✓ Task 2. Sync at a Home-return checkpoint, sweep sessions/obstacles before telemetry (Mission Flow — Completion & sync) ✓ Task 3. The 2026-09-24 SQLite commit-cadence decision is implemented, not just documented — verified by Task 1's durability test using two real SQLite connections to the same file, and the interval itself is a named constant (`DEFAULT_TELEMETRY_COMMIT_INTERVAL_S`) plus a tested decision function (`should_commit_telemetry`), not a number left for some future scheduling loop to hardcode. The live summary telemetry tier (continuous low-rate stream over LoRa/WiFi), the sensor-manifest fetch/cache mechanism itself, and the actual Home-return-triggering logic are explicitly out of scope — Mission Runtime plan.
- **Placeholder scan:** no TBD/TODO; every step has runnable code.
- **Type consistency:** `local_store`'s dict shapes match what `telemetry_record.build_telemetry_record` produces (Task 2's output is fed directly into Task 1's `save_telemetry_record` in Task 4's integration test) and what `sync_client`'s `_*_to_wire` functions consume — no field-name mismatches across the three modules.
