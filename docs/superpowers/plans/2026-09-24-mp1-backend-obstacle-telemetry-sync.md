# MP-1 Backend Obstacle & Telemetry Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Pi something real to sync to — Mongo collections and batch sync endpoints for sweep sessions, obstacles, and telemetry, extending the Backend Core plan's FastAPI+MongoDB service.

**Architecture:** Three new collections, each with a Pydantic model, a service module, and a slice of a shared `/sync` router. Unlike `Rover`/`Geofence`/`Command` (server-generated ObjectIds), these three use **client-generated IDs** — UUIDs the Pi assigns at creation time, since a sweep session or obstacle must exist locally before any connectivity to the backend is guaranteed. That one choice is what makes sync idempotent and retry-safe without separate reconciliation logic: obstacles and sweep sessions sync via upsert (they're mutable — review status changes, sessions transition state), telemetry syncs via insert-only with duplicate-key errors treated as "already synced," since telemetry is append-only and never edited after the fact.

**Tech Stack:** Same as Backend Core — Python 3.12, FastAPI, pymongo (sync), Pydantic v2, pytest, MongoDB Atlas. No new dependencies.

## Global Constraints

- Extends `pathfinder-autonomous/backend/` from the Backend Core plan. Reuses its `db`/`client` pytest fixtures, `ensure_indexes` function, GeoJSON models (`app.models.geo.GeoPoint`), and MongoDB Atlas connection (`.env`'s `MONGO_URI`) — no new infrastructure.
- **Client-generated IDs**: `SweepSession`, `Obstacle`, and `TelemetryRecord` all take `id: str` as a plain client-supplied string (a UUID the Pi generates), not a server-generated `ObjectId`. This is a deliberate asymmetry from Rover/Geofence/Command, and it's what resolves the design spec's "sync reconciliation mechanism" open item — see Architecture above.
- **Obstacle/SweepSession sync = upsert** (`replace_one(..., upsert=True)` per record) — both are mutable over their lifecycle (obstacle review status changes; sweep session status transitions). **Telemetry sync = insert-only** (`insert_many(..., ordered=False)`), with duplicate-key errors (Mongo error code 11000) on retry treated as success, not failure — any other error still raises.
- Telemetry lives in a native MongoDB **time-series collection** (`timeField="timestamp"`, `metaField="rover_id"`), created idempotently — this was already decided in the design spec's Telemetry section, not a new choice here.
- No `synced_at`-style bookkeeping lives on the Mongo side — "has this record been synced" is entirely a Pi-local SQLite concern (the next plan). The backend just accepts idempotent syncs; it doesn't track what the Pi has or hasn't sent yet.
- Human review of `permanent-pending` obstacles (confirm/reject via the UI) is **out of scope for this plan** — this plan adds the read-side `list_pending_review` service function only; the write-side review endpoint belongs to the Management UI plan, which is the first thing that will actually call it.

---

## File Structure

```
pathfinder-autonomous/
  backend/
    app/
      models/
        sweep_session.py   # NEW -- SweepSession, SweepWaypoint, SweepSessionSyncBatch
        obstacle.py          # NEW -- Obstacle, ObstacleSyncBatch
        telemetry.py           # NEW -- TelemetryRecord, TelemetrySyncBatch
      services/
        sweep_sessions.py    # NEW -- sync_sweep_sessions()
        obstacles.py            # NEW -- sync_obstacles(), list_pending_review()
        telemetry.py              # NEW -- sync_telemetry()
      routers/
        sync.py                     # NEW -- POST /sync/sweep-sessions, /sync/obstacles, /sync/telemetry
      db.py                          # MODIFIED -- extend ensure_indexes
      main.py                         # MODIFIED -- register the sync router
    tests/
      test_sweep_session_sync.py       # NEW
      test_obstacle_sync.py              # NEW
      test_telemetry_sync.py               # NEW
      test_sync_router.py                    # NEW
      test_sync_end_to_end.py                  # NEW
```

---

### Task 1: Sweep-session sync

**Files:**
- Create: `pathfinder-autonomous/backend/app/models/sweep_session.py`
- Create: `pathfinder-autonomous/backend/app/services/sweep_sessions.py`
- Test: `pathfinder-autonomous/backend/tests/test_sweep_session_sync.py`
- Modify: `pathfinder-autonomous/backend/app/db.py` (extend `ensure_indexes`)

**Interfaces:**
- Consumes: `app.models.geo.GeoPoint` (Backend Core plan), `app.db.get_database`/`ensure_indexes` (Backend Core plan).
- Produces: `app.models.sweep_session.{SweepWaypoint, SweepSession, SweepSessionSyncBatch}`. `app.services.sweep_sessions.sync_sweep_sessions(db, sessions: list[SweepSession]) -> int` (returns count processed), upserting by client-supplied `id`. Task 4's router wires this to `POST /sync/sweep-sessions`.

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/backend/tests/test_sweep_session_sync.py
from datetime import datetime, timezone

from app.models.geo import GeoPoint
from app.models.sweep_session import SweepSession, SweepWaypoint
from app.services import sweep_sessions as sweep_session_service

STARTED_AT = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


def _session(session_id="sess-uuid-1", status="completed"):
    return SweepSession(
        _id=session_id,
        rover_id="rover-uuid-1",
        geofence_id="fence-uuid-1",
        status=status,
        pattern=[SweepWaypoint(order=0, position=GeoPoint(coordinates=(-85.0, 38.0)))],
        last_completed_waypoint_index=0,
        started_at=STARTED_AT,
        completed_at=STARTED_AT,
    )


def test_sync_sweep_sessions_inserts_new_records(db):
    count = sweep_session_service.sync_sweep_sessions(db, [_session()])

    assert count == 1
    stored = db.sweep_sessions.find_one({"_id": "sess-uuid-1"})
    assert stored is not None
    assert stored["status"] == "completed"


def test_sync_sweep_sessions_upserts_existing_record(db):
    sweep_session_service.sync_sweep_sessions(db, [_session()])

    updated = _session(status="interrupted")
    sweep_session_service.sync_sweep_sessions(db, [updated])

    stored = db.sweep_sessions.find_one({"_id": "sess-uuid-1"})
    assert stored["status"] == "interrupted"
    assert db.sweep_sessions.count_documents({}) == 1  # no duplicate


def test_sync_sweep_sessions_handles_empty_batch(db):
    count = sweep_session_service.sync_sweep_sessions(db, [])

    assert count == 0
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_sweep_session_sync.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.sweep_session'`

- [ ] **Step 3: Write the SweepSession model**

```python
# pathfinder-autonomous/backend/app/models/sweep_session.py
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.geo import GeoPoint


class SweepWaypoint(BaseModel):
    order: int
    position: GeoPoint


class SweepSession(BaseModel):
    id: str = Field(alias="_id")  # client-generated (Pi-assigned UUID)
    rover_id: str
    geofence_id: str
    status: Literal["in_progress", "interrupted", "completed"]
    pattern: list[SweepWaypoint]
    last_completed_waypoint_index: int
    started_at: datetime
    interrupted_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"populate_by_name": True}


class SweepSessionSyncBatch(BaseModel):
    sessions: list[SweepSession]
```

- [ ] **Step 4: Write the sync service**

```python
# pathfinder-autonomous/backend/app/services/sweep_sessions.py
from pymongo.database import Database

from app.models.sweep_session import SweepSession


def sync_sweep_sessions(db: Database, sessions: list[SweepSession]) -> int:
    count = 0
    for session in sessions:
        doc = session.model_dump(by_alias=True)
        db.sweep_sessions.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        count += 1
    return count
```

- [ ] **Step 5: Extend `ensure_indexes` with a sweep-session index**

```python
# pathfinder-autonomous/backend/app/db.py -- add inside ensure_indexes(), after the existing db.commands.create_index(...) line:
    db.sweep_sessions.create_index([("rover_id", ASCENDING)])
```

- [ ] **Step 6: Run the tests and verify they pass**

Run: `pytest tests/test_sweep_session_sync.py -v`
Expected: PASS (3 passed)

- [ ] **Step 7: Commit**

```bash
git add pathfinder-autonomous/backend
git commit -m "feat(backend): add sweep-session sync via client-generated-ID upsert"
```

---

### Task 2: Obstacle sync

**Files:**
- Create: `pathfinder-autonomous/backend/app/models/obstacle.py`
- Create: `pathfinder-autonomous/backend/app/services/obstacles.py`
- Test: `pathfinder-autonomous/backend/tests/test_obstacle_sync.py`
- Modify: `pathfinder-autonomous/backend/app/db.py` (extend `ensure_indexes`)

**Interfaces:**
- Consumes: `app.models.geo.GeoPoint` (Backend Core plan).
- Produces: `app.models.obstacle.{Obstacle, ObstacleSyncBatch}`. `Obstacle` is the backend's persisted counterpart to `papaya_mission.obstacle.Obstacle` (Obstacle Detection & Classification plan) — same shape plus the lifecycle fields that plan deliberately left out (`id`, `sweep_session_id`, `review_status`, `reviewed_by`, `reviewed_at`). `app.services.obstacles.{sync_obstacles(db, obstacles: list[Obstacle]) -> int, list_pending_review(db) -> list[Obstacle]}`. Task 4's router wires `sync_obstacles` to `POST /sync/obstacles`; the Management UI plan will wire `list_pending_review` (and a not-yet-built review-update function) to its review screen.

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/backend/tests/test_obstacle_sync.py
from datetime import datetime, timezone

from app.models.geo import GeoPoint
from app.models.obstacle import Obstacle
from app.services import obstacles as obstacle_service

DETECTED_AT = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


def _obstacle(obstacle_id="obs-uuid-1", status="permanent-pending", review_status="pending"):
    return Obstacle(
        _id=obstacle_id,
        sweep_session_id="sess-uuid-1",
        position=GeoPoint(coordinates=(-85.0005, 38.0005)),
        position_uncertainty_m=1.5,
        type="barrel",
        classification_confidence=0.9,
        detection_method="ultrasonic+camera",
        status=status,
        first_detected_at=DETECTED_AT,
        review_status=review_status,
    )


def test_sync_obstacles_inserts_new_records(db):
    count = obstacle_service.sync_obstacles(db, [_obstacle()])

    assert count == 1
    stored = db.obstacles.find_one({"_id": "obs-uuid-1"})
    assert stored is not None
    assert stored["type"] == "barrel"


def test_sync_obstacles_upserts_existing_record(db):
    obstacle_service.sync_obstacles(db, [_obstacle()])

    confirmed = _obstacle(status="permanent-confirmed", review_status="confirmed")
    obstacle_service.sync_obstacles(db, [confirmed])

    stored = db.obstacles.find_one({"_id": "obs-uuid-1"})
    assert stored["status"] == "permanent-confirmed"
    assert db.obstacles.count_documents({}) == 1


def test_list_pending_review_returns_only_permanent_pending_awaiting_review(db):
    obstacle_service.sync_obstacles(
        db,
        [
            _obstacle(obstacle_id="obs-1", status="permanent-pending", review_status="pending"),
            _obstacle(obstacle_id="obs-2", status="temporary", review_status="pending"),
            _obstacle(obstacle_id="obs-3", status="permanent-pending", review_status="confirmed"),
        ],
    )

    pending = obstacle_service.list_pending_review(db)

    assert [o.id for o in pending] == ["obs-1"]


def test_obstacle_position_supports_geospatial_query(db):
    obstacle_service.sync_obstacles(db, [_obstacle()])

    nearby = list(
        db.obstacles.find(
            {
                "position": {
                    "$near": {
                        "$geometry": {"type": "Point", "coordinates": [-85.0005, 38.0005]},
                        "$maxDistance": 10,
                    }
                }
            }
        )
    )

    assert len(nearby) == 1
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_obstacle_sync.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.obstacle'`

- [ ] **Step 3: Write the Obstacle model**

```python
# pathfinder-autonomous/backend/app/models/obstacle.py
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.geo import GeoPoint


class Obstacle(BaseModel):
    id: str = Field(alias="_id")  # client-generated (Pi-assigned UUID)
    sweep_session_id: str
    position: GeoPoint
    position_uncertainty_m: float
    type: str
    classification_confidence: float
    detection_method: Literal["ultrasonic+camera", "contact-only"]
    status: Literal["temporary", "permanent-pending", "permanent-confirmed"]
    first_detected_at: datetime
    last_confirmed_at: datetime | None = None
    review_status: Literal["pending", "confirmed", "rejected"] = "pending"
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None

    model_config = {"populate_by_name": True}


class ObstacleSyncBatch(BaseModel):
    obstacles: list[Obstacle]
```

- [ ] **Step 4: Write the sync service**

```python
# pathfinder-autonomous/backend/app/services/obstacles.py
from pymongo.database import Database

from app.models.obstacle import Obstacle


def sync_obstacles(db: Database, obstacles: list[Obstacle]) -> int:
    count = 0
    for obstacle in obstacles:
        doc = obstacle.model_dump(by_alias=True)
        db.obstacles.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        count += 1
    return count


def list_pending_review(db: Database) -> list[Obstacle]:
    docs = db.obstacles.find({"status": "permanent-pending", "review_status": "pending"})
    return [Obstacle.model_validate(doc) for doc in docs]
```

- [ ] **Step 5: Extend `ensure_indexes` with a 2dsphere index on obstacle position**

```python
# pathfinder-autonomous/backend/app/db.py -- add inside ensure_indexes(), after db.sweep_sessions.create_index(...):
    db.obstacles.create_index([("position", "2dsphere")])
```

- [ ] **Step 6: Run the tests and verify they pass**

Run: `pytest tests/test_obstacle_sync.py -v`
Expected: PASS (4 passed). If the geospatial test fails, verify `ensure_indexes` ran against the `db` fixture (it does, per `conftest.py`) — `$near` needs the 2dsphere index this step just added.

- [ ] **Step 7: Commit**

```bash
git add pathfinder-autonomous/backend
git commit -m "feat(backend): add obstacle sync and pending-review listing"
```

---

### Task 3: Telemetry sync

**Files:**
- Create: `pathfinder-autonomous/backend/app/models/telemetry.py`
- Create: `pathfinder-autonomous/backend/app/services/telemetry.py`
- Test: `pathfinder-autonomous/backend/tests/test_telemetry_sync.py`
- Modify: `pathfinder-autonomous/backend/app/db.py` (extend `ensure_indexes`)

**Interfaces:**
- Produces: `app.models.telemetry.{TelemetryRecord, TelemetrySyncBatch}`. `app.services.telemetry.sync_telemetry(db, records: list[TelemetryRecord]) -> int` (returns count of *newly* inserted records — already-synced duplicates in the batch don't count). Task 4's router wires this to `POST /sync/telemetry`.

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/backend/tests/test_telemetry_sync.py
from datetime import datetime, timezone

from app.models.telemetry import TelemetryRecord
from app.services import telemetry as telemetry_service

TIMESTAMP = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


def _record(record_id="tel-uuid-1", sequence_number=1):
    return TelemetryRecord(
        _id=record_id,
        rover_id="rover-uuid-1",
        timestamp=TIMESTAMP,
        local_tz_offset_minutes=-300,
        sweep_session_id="sess-uuid-1",
        sequence_number=sequence_number,
        metrics={"battery_voltage": 11.8},
    )


def test_sync_telemetry_inserts_new_records(db):
    count = telemetry_service.sync_telemetry(db, [_record()])

    assert count == 1
    stored = db.telemetry.find_one({"_id": "tel-uuid-1"})
    assert stored is not None
    assert stored["metrics"]["battery_voltage"] == 11.8


def test_sync_telemetry_is_idempotent_on_retry(db):
    telemetry_service.sync_telemetry(db, [_record()])

    # Simulate a retried sync after a dropped connection -- same batch
    # resent. Should not raise, and should not duplicate.
    count = telemetry_service.sync_telemetry(db, [_record()])

    assert count == 0  # nothing NEW was inserted this time
    assert db.telemetry.count_documents({}) == 1


def test_sync_telemetry_partial_retry_only_inserts_new_records(db):
    telemetry_service.sync_telemetry(db, [_record(record_id="tel-uuid-1")])

    # Second batch has one already-synced record and one genuinely new one.
    count = telemetry_service.sync_telemetry(
        db,
        [_record(record_id="tel-uuid-1"), _record(record_id="tel-uuid-2", sequence_number=2)],
    )

    assert count == 1
    assert db.telemetry.count_documents({}) == 2


def test_sync_telemetry_handles_empty_batch(db):
    count = telemetry_service.sync_telemetry(db, [])

    assert count == 0
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_telemetry_sync.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.telemetry'`

- [ ] **Step 3: Write the TelemetryRecord model**

```python
# pathfinder-autonomous/backend/app/models/telemetry.py
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TelemetryRecord(BaseModel):
    id: str = Field(alias="_id")  # client-generated (Pi-assigned UUID) -- guards retries
    rover_id: str
    timestamp: datetime
    local_tz_offset_minutes: int
    sweep_session_id: str | None = None
    sequence_number: int
    metrics: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class TelemetrySyncBatch(BaseModel):
    records: list[TelemetryRecord]
```

- [ ] **Step 4: Write the sync service**

```python
# pathfinder-autonomous/backend/app/services/telemetry.py
from pymongo.database import Database
from pymongo.errors import BulkWriteError

from app.models.telemetry import TelemetryRecord

_DUPLICATE_KEY_ERROR_CODE = 11000


def sync_telemetry(db: Database, records: list[TelemetryRecord]) -> int:
    """Telemetry is append-only -- insert, not upsert. Client-generated
    IDs make retries safe: a duplicate-key error on re-sending an
    already-synced record is expected and ignored, not a failure. Any
    other error still raises.
    """
    if not records:
        return 0

    docs = [record.model_dump(by_alias=True) for record in records]
    try:
        result = db.telemetry.insert_many(docs, ordered=False)
        return len(result.inserted_ids)
    except BulkWriteError as exc:
        write_errors = exc.details.get("writeErrors", [])
        real_errors = [e for e in write_errors if e.get("code") != _DUPLICATE_KEY_ERROR_CODE]
        if real_errors:
            raise
        return len(docs) - len(write_errors)
```

- [ ] **Step 5: Extend `ensure_indexes` to create the telemetry time-series collection**

```python
# pathfinder-autonomous/backend/app/db.py -- add as a new function, and call it from ensure_indexes()
def _ensure_telemetry_timeseries_collection(db: Database) -> None:
    if "telemetry" not in db.list_collection_names():
        db.create_collection(
            "telemetry",
            timeseries={"timeField": "timestamp", "metaField": "rover_id", "granularity": "seconds"},
        )
```

Add `_ensure_telemetry_timeseries_collection(db)` as the last line inside `ensure_indexes()`.

- [ ] **Step 6: Run the tests and verify they pass**

Run: `pytest tests/test_telemetry_sync.py -v`
Expected: PASS (4 passed)

- [ ] **Step 7: Commit**

```bash
git add pathfinder-autonomous/backend
git commit -m "feat(backend): add idempotent telemetry sync into a time-series collection"
```

---

### Task 4: Sync router and end-to-end test

**Files:**
- Create: `pathfinder-autonomous/backend/app/routers/sync.py`
- Modify: `pathfinder-autonomous/backend/app/main.py` (register the sync router)
- Test: `pathfinder-autonomous/backend/tests/test_sync_router.py`
- Test: `pathfinder-autonomous/backend/tests/test_sync_end_to_end.py`

**Interfaces:**
- Consumes: Tasks 1–3's services.
- Produces: `POST /sync/sweep-sessions`, `POST /sync/obstacles`, `POST /sync/telemetry` — each accepts the corresponding `*SyncBatch` model, returns `{"synced": <count>}`.

- [ ] **Step 1: Write the failing router tests**

```python
# pathfinder-autonomous/backend/tests/test_sync_router.py
def test_sync_sweep_sessions_endpoint(client):
    payload = {
        "sessions": [
            {
                "_id": "sess-uuid-1",
                "rover_id": "rover-uuid-1",
                "geofence_id": "fence-uuid-1",
                "status": "completed",
                "pattern": [
                    {"order": 0, "position": {"type": "Point", "coordinates": [-85.0, 38.0]}}
                ],
                "last_completed_waypoint_index": 0,
                "started_at": "2026-09-24T12:00:00Z",
                "completed_at": "2026-09-24T12:30:00Z",
            }
        ]
    }

    response = client.post("/sync/sweep-sessions", json=payload)

    assert response.status_code == 200
    assert response.json() == {"synced": 1}


def test_sync_obstacles_endpoint(client):
    payload = {
        "obstacles": [
            {
                "_id": "obs-uuid-1",
                "sweep_session_id": "sess-uuid-1",
                "position": {"type": "Point", "coordinates": [-85.0005, 38.0005]},
                "position_uncertainty_m": 1.5,
                "type": "barrel",
                "classification_confidence": 0.9,
                "detection_method": "ultrasonic+camera",
                "status": "permanent-pending",
                "first_detected_at": "2026-09-24T12:01:00Z",
            }
        ]
    }

    response = client.post("/sync/obstacles", json=payload)

    assert response.status_code == 200
    assert response.json() == {"synced": 1}


def test_sync_telemetry_endpoint(client):
    payload = {
        "records": [
            {
                "_id": "tel-uuid-1",
                "rover_id": "rover-uuid-1",
                "timestamp": "2026-09-24T12:00:05Z",
                "local_tz_offset_minutes": -300,
                "sweep_session_id": "sess-uuid-1",
                "sequence_number": 1,
                "metrics": {"battery_voltage": 11.8},
            }
        ]
    }

    response = client.post("/sync/telemetry", json=payload)

    assert response.status_code == 200
    assert response.json() == {"synced": 1}
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_sync_router.py -v`
Expected: FAIL — `404 != 200` (no `/sync` routes registered yet).

- [ ] **Step 3: Write the sync router and register it**

```python
# pathfinder-autonomous/backend/app/routers/sync.py
from fastapi import APIRouter, Depends
from pymongo.database import Database

from app.db import get_database
from app.models.obstacle import ObstacleSyncBatch
from app.models.sweep_session import SweepSessionSyncBatch
from app.models.telemetry import TelemetrySyncBatch
from app.services import obstacles as obstacle_service
from app.services import sweep_sessions as sweep_session_service
from app.services import telemetry as telemetry_service

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/sweep-sessions")
def sync_sweep_sessions(
    batch: SweepSessionSyncBatch, db: Database = Depends(get_database)
) -> dict[str, int]:
    count = sweep_session_service.sync_sweep_sessions(db, batch.sessions)
    return {"synced": count}


@router.post("/obstacles")
def sync_obstacles(batch: ObstacleSyncBatch, db: Database = Depends(get_database)) -> dict[str, int]:
    count = obstacle_service.sync_obstacles(db, batch.obstacles)
    return {"synced": count}


@router.post("/telemetry")
def sync_telemetry(batch: TelemetrySyncBatch, db: Database = Depends(get_database)) -> dict[str, int]:
    count = telemetry_service.sync_telemetry(db, batch.records)
    return {"synced": count}
```

```python
# pathfinder-autonomous/backend/app/main.py
from fastapi import FastAPI

from app.db import ensure_indexes, get_client, get_database
from app.routers import commands, geofences, rovers, sync

app = FastAPI(title="Papaya Pathfinder Backend")

app.include_router(rovers.router)
app.include_router(geofences.router)
app.include_router(commands.router)
app.include_router(sync.router)


@app.on_event("startup")
def on_startup() -> None:
    db = get_database(get_client())
    ensure_indexes(db)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: Run the router tests and verify they pass**

Run: `pytest tests/test_sync_router.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Write the end-to-end sync test**

Walks a realistic full-mission sync: a rover and geofence exist, a sweep session and the obstacles/telemetry it produced all sync together, then a simulated retry proves idempotency.

```python
# pathfinder-autonomous/backend/tests/test_sync_end_to_end.py
def test_full_mission_sync_then_idempotent_retry(client):
    rover_id = client.post("/rovers", json={"name": "George"}).json()["_id"]
    field = client.post(
        "/geofences",
        json={
            "type": "inclusive",
            "name": "Main field",
            "boundary": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-85.001, 38.000],
                        [-85.001, 38.001],
                        [-85.000, 38.001],
                        [-85.000, 38.000],
                        [-85.001, 38.000],
                    ]
                ],
            },
        },
    ).json()

    sweep_session_payload = {
        "sessions": [
            {
                "_id": "sess-uuid-1",
                "rover_id": rover_id,
                "geofence_id": field["_id"],
                "status": "completed",
                "pattern": [
                    {"order": 0, "position": {"type": "Point", "coordinates": [-85.0, 38.0]}}
                ],
                "last_completed_waypoint_index": 0,
                "started_at": "2026-09-24T12:00:00Z",
                "completed_at": "2026-09-24T12:30:00Z",
            }
        ]
    }
    obstacle_payload = {
        "obstacles": [
            {
                "_id": "obs-uuid-1",
                "sweep_session_id": "sess-uuid-1",
                "position": {"type": "Point", "coordinates": [-85.0005, 38.0005]},
                "position_uncertainty_m": 1.5,
                "type": "barrel",
                "classification_confidence": 0.9,
                "detection_method": "ultrasonic+camera",
                "status": "permanent-pending",
                "first_detected_at": "2026-09-24T12:01:00Z",
            }
        ]
    }
    telemetry_payload = {
        "records": [
            {
                "_id": "tel-uuid-1",
                "rover_id": rover_id,
                "timestamp": "2026-09-24T12:00:05Z",
                "local_tz_offset_minutes": -300,
                "sweep_session_id": "sess-uuid-1",
                "sequence_number": 1,
                "metrics": {"battery_voltage": 11.8},
            }
        ]
    }

    first_pass = [
        client.post("/sync/sweep-sessions", json=sweep_session_payload),
        client.post("/sync/obstacles", json=obstacle_payload),
        client.post("/sync/telemetry", json=telemetry_payload),
    ]
    assert all(r.status_code == 200 and r.json() == {"synced": 1} for r in first_pass)

    # Simulate the connection dropping right after a successful sync, and
    # the rover retrying the same batch on its next Home-return checkpoint.
    retry = [
        client.post("/sync/sweep-sessions", json=sweep_session_payload),
        client.post("/sync/obstacles", json=obstacle_payload),
        client.post("/sync/telemetry", json=telemetry_payload),
    ]
    assert retry[0].json() == {"synced": 1}  # upsert -- still "processed", no duplicate created
    assert retry[1].json() == {"synced": 1}  # upsert -- same
    assert retry[2].json() == {"synced": 0}  # insert-only -- correctly reports nothing NEW
```

- [ ] **Step 6: Run it and verify it passes**

Run: `pytest tests/test_sync_end_to_end.py -v`
Expected: PASS

- [ ] **Step 7: Run the full test suite and verify zero regressions**

Run: `pytest -v`
Expected: PASS — every test from the Backend Core plan plus everything from this plan.

- [ ] **Step 8: Commit**

```bash
git add pathfinder-autonomous/backend
git commit -m "feat(backend): wire sweep-session/obstacle/telemetry sync into the API"
```

---

## Self-Review Notes

- **Spec coverage:** Sweep session, obstacle, and telemetry all sync to MongoDB as the authoritative store (Data Model — Local vs. Mongo storage) ✓ Tasks 1–3. Telemetry uses a native time-series collection (Telemetry — Mongo storage) ✓ Task 3. Obstacle 2dsphere indexing for future geospatial queries (consistent with Geofence's pattern from Backend Core) ✓ Task 2. Resolves the "sync reconciliation mechanism" open item via client-generated IDs + idempotent upsert/insert, verified explicitly by Task 4's retry test. Human review-workflow write endpoints, the Pi-side local SQLite store, and the actual sync *client* (what decides when to call these endpoints, and from what local data) are explicitly out of scope — the Pi Local Store & Sync Client plan and the Management UI plan.
- **Placeholder scan:** no TBD/TODO; every step has runnable code.
- **Type consistency:** `Obstacle.position`/`SweepWaypoint.position` use `GeoPoint` from Backend Core's `app.models.geo`, same as `Geofence.boundary` uses `GeoPolygon` — consistent GeoJSON convention across every collection. All three new models use `id: str = Field(alias="_id")` with client-generated values, consistently distinct from Rover/Geofence/Command's server-generated `ObjectId`-backed pattern — documented explicitly in Global Constraints so this isn't mistaken for an oversight later.
