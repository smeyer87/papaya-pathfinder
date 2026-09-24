# MP-1 Backend Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the local, container-hosted backend data layer and API that everything else in MP-1 depends on — the MongoDB schema (with GeoJSON/2dsphere geospatial support), the Rover fleet registry, Geofence CRUD, and the polled command-queue API.

**Architecture:** A FastAPI service, running in Docker Compose on a home-network host, backed by MongoDB Atlas (hosted, managed separately). Business logic lives in a `services/` layer that talks to `pymongo` directly (testable without an HTTP client); thin FastAPI routers translate service-layer exceptions into HTTP responses. No mocking of MongoDB — every test runs against a real Mongo instance (Atlas dev cluster or a disposable local container), because this plan's core correctness properties (the one-active-rover uniqueness constraint, 2dsphere geo queries) are exactly the things an in-memory mock gets wrong.

**Tech Stack:** Python 3.12, FastAPI, pymongo (sync), Pydantic v2, pytest, Docker Compose, MongoDB Atlas (hosted; a local MongoDB 7 container is used only for local dev/test, never for the target deployment).

## Global Constraints

- New code lives under a new root folder `pathfinder-autonomous/`, physically separate from the existing upstream-derived `pathfinder/` tree (user decision — keeps a future upstream PR or private fork clean). This plan's code lives at `pathfinder-autonomous/backend/`.
- All position/polygon fields use GeoJSON. **Coordinate order is `[longitude, latitude]`** — reversed from casual lat/long usage. (Design spec: Data Model.)
- MongoDB is hosted on **MongoDB Atlas** (managed, hosted — not a self-hosted container), configured manually by the user starting on the Free Tier. Connection details (URI with embedded username/password) come from a `.env` file — never hardcoded in `docker-compose.yml` or committed to git. `.env.example` ships with placeholders for the user to fill in. Local dev/test may point at a disposable local Mongo container or a personal Atlas dev cluster — the application code is identical either way, since it's just a connection string. (User correction, 2026-09-24.)
- The command channel is a **polled queue**, not a push connection — the rover polls for its own commands; the backend never initiates a connection to the rover. (Design spec: Command Channel.)
- Only one Rover may have `status="active"` at any time; starting a mission (`start_sweep`) on a rover while another is active must be rejected. (Design spec: Rover Identity & Fleet.)
- This plan defines exactly three collections: `rovers`, `geofences`, `commands`. Obstacle and telemetry collections belong to later plans (Pi mission core / Pi telemetry + sync) and are out of scope here.

---

## File Structure

```
pathfinder-autonomous/
  backend/
    requirements.txt
    Dockerfile
    docker-compose.yml
    .env.example
    .gitignore
    app/
      __init__.py
      main.py                 # FastAPI app, startup index creation, /health
      db.py                   # Mongo client/database access, ensure_indexes()
      models/
        __init__.py
        geo.py                 # GeoPoint, GeoPolygon (GeoJSON)
        rover.py                # Rover, RoverCreate, RoverUpdate, SensorManifestEntry
        geofence.py             # Geofence, GeofenceCreate
        command.py               # Command, CommandCreate, CommandType
      services/
        __init__.py
        rovers.py                # create/get/list/update/activate/deactivate + exceptions
        geofences.py              # create/get/list + point_in_any_exclusive_zone
        commands.py                # enqueue/poll/ack
      routers/
        __init__.py
        rovers.py
        geofences.py
        commands.py
    tests/
      __init__.py
      conftest.py               # db + client fixtures (real Mongo, per-test DB drop)
      test_health.py
      test_models_geo.py
      test_rover_service.py
      test_rover_router.py
      test_geofence_service.py
      test_geofence_geospatial.py
      test_command_service.py
      test_end_to_end_flow.py
```

---

### Task 1: Project scaffolding, Docker Compose, and health check

**Files:**
- Create: `pathfinder-autonomous/backend/requirements.txt`
- Create: `pathfinder-autonomous/backend/Dockerfile`
- Create: `pathfinder-autonomous/backend/docker-compose.yml`
- Create: `pathfinder-autonomous/backend/.env.example`
- Create: `pathfinder-autonomous/backend/.gitignore`
- Create: `pathfinder-autonomous/backend/app/__init__.py`
- Create: `pathfinder-autonomous/backend/app/db.py`
- Create: `pathfinder-autonomous/backend/app/main.py`
- Create: `pathfinder-autonomous/backend/tests/__init__.py`
- Create: `pathfinder-autonomous/backend/tests/conftest.py`
- Test: `pathfinder-autonomous/backend/tests/test_health.py`

**Interfaces:**
- Produces: `app.db.get_client() -> MongoClient`, `app.db.get_database(client: MongoClient | None = None) -> Database`, `app.db.ensure_indexes(db: Database) -> None` (empty for now, extended in Tasks 3–5). `app.main.app` (the FastAPI instance). Test fixtures `db` and `client` in `tests/conftest.py`, reused by every later task's tests.

- [ ] **Step 1: Create the backend directory and dependency/container files**

`pathfinder-autonomous/backend/requirements.txt`:

```
fastapi==0.115.0
uvicorn[standard]==0.32.0
pymongo==4.9.1
pydantic==2.9.2
pytest==8.3.3
httpx==0.27.2
python-dotenv==1.0.1
```

`pathfinder-autonomous/backend/Dockerfile`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

`pathfinder-autonomous/backend/docker-compose.yml` — just the backend service; MongoDB is Atlas-hosted, external to this compose file, configured via `.env`:

```yaml
services:
  backend:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
```

`pathfinder-autonomous/backend/.env.example` — copy to `.env` and fill in real values; `.env` itself is gitignored:

```
# MongoDB Atlas connection string, from your cluster's "Connect" dialog
# (Database > Connect > Drivers). Includes username and password embedded
# in the URI -- that's the standard Atlas/pymongo pattern, not a Papaya
# Pathfinder-specific choice.
MONGO_URI=mongodb+srv://<username>:<password>@<cluster-host>.mongodb.net/?retryWrites=true&w=majority
MONGO_DB_NAME=papaya_pathfinder
```

`pathfinder-autonomous/backend/.gitignore`:

```
.env
.venv/
__pycache__/
*.pyc
```

- [ ] **Step 2: Set up a Python virtual environment, install dependencies, and create your local `.env`**

Run:
```bash
cd pathfinder-autonomous/backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with either (a) your MongoDB Atlas Free Tier connection string, or (b) `MONGO_URI=mongodb://localhost:27017` if you'd rather run a disposable local Mongo for now (see Step 3) — the code doesn't care which, since both are read from the same `MONGO_URI` value. Using your production Atlas cluster for routine test runs isn't recommended: the test suite creates and drops a `papaya_pathfinder_test` database on whatever cluster `MONGO_URI` points to, on every run.

- [ ] **Step 3: Get a MongoDB instance running for local dev/test**

Either:
- **Atlas Free Tier** — create a cluster in the Atlas UI, create a database user, and use its connection string in `.env` (this is the manually-configured Atlas cluster the user is setting up separately).
- **Local disposable Mongo** — for fast local iteration without touching Atlas at all:
  ```bash
  docker run --rm -d -p 27017:27017 --name papaya-dev-mongo mongo:7
  ```
  and set `MONGO_URI=mongodb://localhost:27017` in `.env`.

Expected either way: you have a `MONGO_URI` in `.env` that a MongoDB client can connect to. Verify with: `python3 -c "from pymongo import MongoClient; import os; from dotenv import load_dotenv; load_dotenv(); MongoClient(os.environ['MONGO_URI']).admin.command('ping')"` — expect no exception.

- [ ] **Step 4: Write the minimal `app/db.py`**

```python
# pathfinder-autonomous/backend/app/db.py
import os

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.database import Database

load_dotenv()


def get_client() -> MongoClient:
    uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
    return MongoClient(uri)


def get_database(client: MongoClient | None = None) -> Database:
    client = client or get_client()
    db_name = os.environ.get("MONGO_DB_NAME", "papaya_pathfinder")
    return client[db_name]


def ensure_indexes(db: Database) -> None:
    """Create/verify all indexes this service depends on.

    Extended in later tasks (rovers' one-active partial unique index,
    geofences' 2dsphere index). Empty for now -- no collections defined yet.
    """
    pass
```

- [ ] **Step 5: Write `app/main.py` with the FastAPI app instance (no `/health` route yet)**

```python
# pathfinder-autonomous/backend/app/main.py
from fastapi import FastAPI

from app.db import ensure_indexes, get_client, get_database

app = FastAPI(title="Papaya Pathfinder Backend")


@app.on_event("startup")
def on_startup() -> None:
    db = get_database(get_client())
    ensure_indexes(db)
```

- [ ] **Step 6: Write the test fixtures in `tests/conftest.py`**

Every later task's tests reuse these two fixtures. `db` gives direct `pymongo` access for service-layer tests; `client` gives a FastAPI `TestClient` wired to the same test database, for router-layer tests.

```python
# pathfinder-autonomous/backend/tests/conftest.py
import os

import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient

from app.db import ensure_indexes, get_database
from app.main import app

TEST_MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
TEST_DB_NAME = "papaya_pathfinder_test"


@pytest.fixture
def db():
    mongo_client = MongoClient(TEST_MONGO_URI)
    database = mongo_client[TEST_DB_NAME]
    ensure_indexes(database)
    yield database
    mongo_client.drop_database(TEST_DB_NAME)
    mongo_client.close()


@pytest.fixture
def client(db):
    app.dependency_overrides[get_database] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
```

Also create the empty `pathfinder-autonomous/backend/tests/__init__.py` and `pathfinder-autonomous/backend/app/__init__.py` (both zero-byte files — they just mark the directories as packages so `pytest` and `app.x` imports resolve).

- [ ] **Step 7: Write the failing test for `/health`**

```python
# pathfinder-autonomous/backend/tests/test_health.py
def test_health_returns_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 8: Run the test and verify it fails**

Run: `pytest tests/test_health.py -v`
Expected: FAIL — `404 != 200` (no `/health` route registered yet).

- [ ] **Step 9: Add the `/health` route to `app/main.py`**

```python
# pathfinder-autonomous/backend/app/main.py
from fastapi import FastAPI

from app.db import ensure_indexes, get_client, get_database

app = FastAPI(title="Papaya Pathfinder Backend")


@app.on_event("startup")
def on_startup() -> None:
    db = get_database(get_client())
    ensure_indexes(db)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 10: Run the test and verify it passes**

Run: `pytest tests/test_health.py -v`
Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add pathfinder-autonomous/backend
git commit -m "feat(backend): scaffold FastAPI+Mongo backend with health check"
```

---

### Task 2: GeoJSON models

**Files:**
- Create: `pathfinder-autonomous/backend/app/models/__init__.py`
- Create: `pathfinder-autonomous/backend/app/models/geo.py`
- Test: `pathfinder-autonomous/backend/tests/test_models_geo.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `app.models.geo.GeoPoint` (fields: `type: Literal["Point"]`, `coordinates: tuple[float, float]` as `[longitude, latitude]`) and `app.models.geo.GeoPolygon` (fields: `type: Literal["Polygon"]`, `coordinates: list[list[tuple[float, float]]]`, one list of closed rings). Both raise `pydantic.ValidationError` on bad input. Used by `app/models/geofence.py` (Task 5) for the `boundary` field, and will be reused by the Pi mission core plan for obstacle/waypoint positions.

- [ ] **Step 1: Write the failing tests**

```python
# pathfinder-autonomous/backend/tests/test_models_geo.py
import pytest
from pydantic import ValidationError

from app.models.geo import GeoPoint, GeoPolygon


def test_geo_point_valid():
    point = GeoPoint(coordinates=(-85.654321, 38.123456))

    assert point.type == "Point"
    assert point.coordinates == (-85.654321, 38.123456)


def test_geo_point_rejects_out_of_range_longitude():
    with pytest.raises(ValidationError):
        GeoPoint(coordinates=(200.0, 38.123456))


def test_geo_point_rejects_out_of_range_latitude():
    with pytest.raises(ValidationError):
        GeoPoint(coordinates=(-85.654321, 95.0))


def test_geo_polygon_valid_closed_ring():
    ring = [(-85.0, 38.0), (-85.0, 38.1), (-84.9, 38.1), (-84.9, 38.0), (-85.0, 38.0)]

    polygon = GeoPolygon(coordinates=[ring])

    assert polygon.type == "Polygon"
    assert polygon.coordinates == [ring]


def test_geo_polygon_rejects_unclosed_ring():
    ring = [(-85.0, 38.0), (-85.0, 38.1), (-84.9, 38.1), (-84.9, 38.0)]

    with pytest.raises(ValidationError):
        GeoPolygon(coordinates=[ring])


def test_geo_polygon_rejects_too_few_points():
    ring = [(-85.0, 38.0), (-85.0, 38.1), (-85.0, 38.0)]

    with pytest.raises(ValidationError):
        GeoPolygon(coordinates=[ring])
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_models_geo.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models'`

- [ ] **Step 3: Write the minimal implementation**

```python
# pathfinder-autonomous/backend/app/models/__init__.py
```

```python
# pathfinder-autonomous/backend/app/models/geo.py
from typing import Literal

from pydantic import BaseModel, field_validator


class GeoPoint(BaseModel):
    """A GeoJSON Point. coordinates is [longitude, latitude] -- NOT lat/long."""

    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]

    @field_validator("coordinates")
    @classmethod
    def validate_ranges(cls, v: tuple[float, float]) -> tuple[float, float]:
        lon, lat = v
        if not (-180.0 <= lon <= 180.0):
            raise ValueError(f"longitude {lon} out of range [-180, 180]")
        if not (-90.0 <= lat <= 90.0):
            raise ValueError(f"latitude {lat} out of range [-90, 90]")
        return v


class GeoPolygon(BaseModel):
    """A GeoJSON Polygon. Each ring's positions are [longitude, latitude]."""

    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[tuple[float, float]]]

    @field_validator("coordinates")
    @classmethod
    def validate_rings(
        cls, v: list[list[tuple[float, float]]]
    ) -> list[list[tuple[float, float]]]:
        if not v:
            raise ValueError("polygon must have at least one ring")
        for ring in v:
            if len(ring) < 4:
                raise ValueError(
                    "each polygon ring needs at least 4 positions (closed ring)"
                )
            if ring[0] != ring[-1]:
                raise ValueError(
                    "polygon ring must be closed (first position == last position)"
                )
        return v
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_models_geo.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add pathfinder-autonomous/backend/app/models pathfinder-autonomous/backend/tests/test_models_geo.py
git commit -m "feat(backend): add GeoJSON Point/Polygon models with validation"
```

---

### Task 3: Rover registry

**Files:**
- Create: `pathfinder-autonomous/backend/app/models/rover.py`
- Create: `pathfinder-autonomous/backend/app/services/__init__.py`
- Create: `pathfinder-autonomous/backend/app/services/rovers.py`
- Create: `pathfinder-autonomous/backend/app/routers/__init__.py`
- Create: `pathfinder-autonomous/backend/app/routers/rovers.py`
- Modify: `pathfinder-autonomous/backend/app/db.py` (extend `ensure_indexes`)
- Modify: `pathfinder-autonomous/backend/app/main.py` (register the rovers router)
- Test: `pathfinder-autonomous/backend/tests/test_rover_service.py`
- Test: `pathfinder-autonomous/backend/tests/test_rover_router.py`

**Interfaces:**
- Consumes: `app.db.get_database` (Task 1), pytest `db`/`client` fixtures (Task 1).
- Produces: `app.models.rover.{Rover, RoverCreate, RoverUpdate, SensorManifestEntry}`. Service functions in `app.services.rovers`: `create_rover(db, data: RoverCreate) -> Rover`, `get_rover(db, rover_id: str) -> Rover`, `list_rovers(db) -> list[Rover]`, `update_rover(db, rover_id, data: RoverUpdate) -> Rover`, `activate_rover(db, rover_id) -> Rover`, `deactivate_rover(db, rover_id) -> Rover`. Exceptions: `RoverNotFound`, `AnotherRoverActive(active_rover_id: str)`. Router mounted at `/rovers`. Task 4's `commands.py` service calls `activate_rover`/`deactivate_rover`/`get_rover` directly.

- [ ] **Step 1: Write the failing service-layer tests**

```python
# pathfinder-autonomous/backend/tests/test_rover_service.py
import pytest

from app.models.rover import RoverCreate, RoverUpdate, SensorManifestEntry
from app.services import rovers as rover_service


def test_create_and_get_rover(db):
    created = rover_service.create_rover(
        db, RoverCreate(name="George", supported_mission_packages=["MP-1"])
    )

    fetched = rover_service.get_rover(db, created.id)

    assert fetched.name == "George"
    assert fetched.supported_mission_packages == ["MP-1"]
    assert fetched.status == "inactive"


def test_get_rover_not_found_raises(db):
    with pytest.raises(rover_service.RoverNotFound):
        rover_service.get_rover(db, "000000000000000000000000")


def test_list_rovers_returns_all(db):
    rover_service.create_rover(db, RoverCreate(name="George"))
    rover_service.create_rover(db, RoverCreate(name="Rover2"))

    rovers = rover_service.list_rovers(db)

    assert {r.name for r in rovers} == {"George", "Rover2"}


def test_update_rover_sensor_manifest(db):
    created = rover_service.create_rover(db, RoverCreate(name="George"))

    updated = rover_service.update_rover(
        db,
        created.id,
        RoverUpdate(
            sensor_manifest=[SensorManifestEntry(sensor="gps", installed=True)]
        ),
    )

    assert updated.sensor_manifest[0].sensor == "gps"
    assert updated.name == "George"  # untouched field preserved


def test_activate_rover_sets_status_active(db):
    created = rover_service.create_rover(db, RoverCreate(name="George"))

    activated = rover_service.activate_rover(db, created.id)

    assert activated.status == "active"


def test_activate_second_rover_while_first_active_raises(db):
    first = rover_service.create_rover(db, RoverCreate(name="George"))
    second = rover_service.create_rover(db, RoverCreate(name="Rover2"))
    rover_service.activate_rover(db, first.id)

    with pytest.raises(rover_service.AnotherRoverActive) as exc_info:
        rover_service.activate_rover(db, second.id)

    assert exc_info.value.active_rover_id == first.id


def test_deactivate_then_activate_another_succeeds(db):
    first = rover_service.create_rover(db, RoverCreate(name="George"))
    second = rover_service.create_rover(db, RoverCreate(name="Rover2"))
    rover_service.activate_rover(db, first.id)

    rover_service.deactivate_rover(db, first.id)
    activated_second = rover_service.activate_rover(db, second.id)

    assert activated_second.status == "active"


def test_reactivating_the_same_rover_is_a_safe_no_op(db):
    created = rover_service.create_rover(db, RoverCreate(name="George"))
    rover_service.activate_rover(db, created.id)

    result = rover_service.activate_rover(db, created.id)

    assert result.status == "active"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_rover_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services'`

- [ ] **Step 3: Write the Rover models**

```python
# pathfinder-autonomous/backend/app/models/rover.py
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SensorManifestEntry(BaseModel):
    sensor: str  # e.g. "gps", "imu", "ultrasonic", "ai_camera", "bump"
    installed: bool = True


class Rover(BaseModel):
    id: str = Field(alias="_id")
    name: str
    sensor_manifest: list[SensorManifestEntry] = Field(default_factory=list)
    supported_mission_packages: list[str] = Field(default_factory=list)
    status: Literal["active", "inactive"] = "inactive"
    notes: str = ""
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}


class RoverCreate(BaseModel):
    name: str
    sensor_manifest: list[SensorManifestEntry] = Field(default_factory=list)
    supported_mission_packages: list[str] = Field(default_factory=list)
    notes: str = ""


class RoverUpdate(BaseModel):
    name: str | None = None
    sensor_manifest: list[SensorManifestEntry] | None = None
    supported_mission_packages: list[str] | None = None
    notes: str | None = None
```

- [ ] **Step 4: Write the Rover service**

```python
# pathfinder-autonomous/backend/app/services/__init__.py
```

```python
# pathfinder-autonomous/backend/app/services/rovers.py
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.models.rover import Rover, RoverCreate, RoverUpdate


class RoverNotFound(Exception):
    def __init__(self, rover_id: str):
        self.rover_id = rover_id
        super().__init__(f"rover {rover_id} not found")


class AnotherRoverActive(Exception):
    def __init__(self, active_rover_id: str):
        self.active_rover_id = active_rover_id
        super().__init__(f"rover {active_rover_id} is already active")


def _to_object_id(rover_id: str) -> ObjectId:
    try:
        return ObjectId(rover_id)
    except InvalidId as exc:
        raise RoverNotFound(rover_id) from exc


def _doc_to_rover(doc: dict) -> Rover:
    doc = dict(doc)
    doc["_id"] = str(doc["_id"])
    return Rover.model_validate(doc)


def create_rover(db: Database, data: RoverCreate) -> Rover:
    now = _utcnow()
    doc = data.model_dump()
    doc["status"] = "inactive"
    doc["created_at"] = now
    doc["updated_at"] = now
    result = db.rovers.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _doc_to_rover(doc)


def get_rover(db: Database, rover_id: str) -> Rover:
    doc = db.rovers.find_one({"_id": _to_object_id(rover_id)})
    if doc is None:
        raise RoverNotFound(rover_id)
    return _doc_to_rover(doc)


def list_rovers(db: Database) -> list[Rover]:
    return [_doc_to_rover(doc) for doc in db.rovers.find()]


def update_rover(db: Database, rover_id: str, data: RoverUpdate) -> Rover:
    updates = {
        key: value
        for key, value in data.model_dump(exclude_unset=True).items()
        if value is not None
    }
    if updates:
        updates["updated_at"] = _utcnow()
        result = db.rovers.update_one(
            {"_id": _to_object_id(rover_id)}, {"$set": updates}
        )
        if result.matched_count == 0:
            raise RoverNotFound(rover_id)
    return get_rover(db, rover_id)


def activate_rover(db: Database, rover_id: str) -> Rover:
    object_id = _to_object_id(rover_id)
    try:
        result = db.rovers.update_one(
            {"_id": object_id},
            {"$set": {"status": "active", "updated_at": _utcnow()}},
        )
    except DuplicateKeyError as exc:
        active_doc = db.rovers.find_one({"status": "active"})
        active_id = str(active_doc["_id"]) if active_doc else "unknown"
        raise AnotherRoverActive(active_id) from exc
    if result.matched_count == 0:
        raise RoverNotFound(rover_id)
    return get_rover(db, rover_id)


def deactivate_rover(db: Database, rover_id: str) -> Rover:
    result = db.rovers.update_one(
        {"_id": _to_object_id(rover_id)},
        {"$set": {"status": "inactive", "updated_at": _utcnow()}},
    )
    if result.matched_count == 0:
        raise RoverNotFound(rover_id)
    return get_rover(db, rover_id)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
```

- [ ] **Step 5: Extend `ensure_indexes` with the one-active-rover partial unique index**

```python
# pathfinder-autonomous/backend/app/db.py
import os

from pymongo import ASCENDING, MongoClient
from pymongo.database import Database


def get_client() -> MongoClient:
    uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
    return MongoClient(uri)


def get_database(client: MongoClient | None = None) -> Database:
    client = client or get_client()
    db_name = os.environ.get("MONGO_DB_NAME", "papaya_pathfinder")
    return client[db_name]


def ensure_indexes(db: Database) -> None:
    db.rovers.create_index(
        [("status", ASCENDING)],
        unique=True,
        partialFilterExpression={"status": "active"},
        name="uniq_active_rover",
    )
```

- [ ] **Step 6: Run the service tests and verify they pass**

Run: `pytest tests/test_rover_service.py -v`
Expected: PASS (7 passed)

- [ ] **Step 7: Write the failing router-layer test**

```python
# pathfinder-autonomous/backend/tests/test_rover_router.py
def test_create_get_list_update_rover_via_api(client):
    create_response = client.post("/rovers", json={"name": "George"})
    assert create_response.status_code == 201
    rover_id = create_response.json()["_id"]

    get_response = client.get(f"/rovers/{rover_id}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "George"

    list_response = client.get("/rovers")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    update_response = client.patch(f"/rovers/{rover_id}", json={"notes": "prototype A"})
    assert update_response.status_code == 200
    assert update_response.json()["notes"] == "prototype A"


def test_get_unknown_rover_returns_404(client):
    response = client.get("/rovers/000000000000000000000000")

    assert response.status_code == 404
```

- [ ] **Step 8: Run the router test and verify it fails**

Run: `pytest tests/test_rover_router.py -v`
Expected: FAIL — `404 != 201` (no `/rovers` route registered yet).

- [ ] **Step 9: Write the Rover router and register it**

```python
# pathfinder-autonomous/backend/app/routers/__init__.py
```

```python
# pathfinder-autonomous/backend/app/routers/rovers.py
from fastapi import APIRouter, Depends, HTTPException
from pymongo.database import Database

from app.db import get_database
from app.models.rover import Rover, RoverCreate, RoverUpdate
from app.services import rovers as rover_service

router = APIRouter(prefix="/rovers", tags=["rovers"])


@router.post("", response_model=Rover, status_code=201)
def create_rover(data: RoverCreate, db: Database = Depends(get_database)) -> Rover:
    return rover_service.create_rover(db, data)


@router.get("", response_model=list[Rover])
def list_rovers(db: Database = Depends(get_database)) -> list[Rover]:
    return rover_service.list_rovers(db)


@router.get("/{rover_id}", response_model=Rover)
def get_rover(rover_id: str, db: Database = Depends(get_database)) -> Rover:
    try:
        return rover_service.get_rover(db, rover_id)
    except rover_service.RoverNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{rover_id}", response_model=Rover)
def update_rover(
    rover_id: str, data: RoverUpdate, db: Database = Depends(get_database)
) -> Rover:
    try:
        return rover_service.update_rover(db, rover_id, data)
    except rover_service.RoverNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
```

```python
# pathfinder-autonomous/backend/app/main.py
from fastapi import FastAPI

from app.db import ensure_indexes, get_client, get_database
from app.routers import rovers

app = FastAPI(title="Papaya Pathfinder Backend")

app.include_router(rovers.router)


@app.on_event("startup")
def on_startup() -> None:
    db = get_database(get_client())
    ensure_indexes(db)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 10: Run the router tests and verify they pass**

Run: `pytest tests/test_rover_router.py -v`
Expected: PASS (2 passed)

- [ ] **Step 11: Run the full test suite to check for regressions**

Run: `pytest -v`
Expected: PASS (all tests, including Tasks 1–2, still green)

- [ ] **Step 12: Commit**

```bash
git add pathfinder-autonomous/backend
git commit -m "feat(backend): add rover registry with one-active-rover invariant"
```

---

### Task 4: Geofence CRUD with geospatial indexing

**Files:**
- Create: `pathfinder-autonomous/backend/app/models/geofence.py`
- Create: `pathfinder-autonomous/backend/app/services/geofences.py`
- Create: `pathfinder-autonomous/backend/app/routers/geofences.py`
- Modify: `pathfinder-autonomous/backend/app/db.py` (extend `ensure_indexes`)
- Modify: `pathfinder-autonomous/backend/app/main.py` (register the geofences router)
- Test: `pathfinder-autonomous/backend/tests/test_geofence_service.py`
- Test: `pathfinder-autonomous/backend/tests/test_geofence_geospatial.py`

**Interfaces:**
- Consumes: `app.models.geo.GeoPolygon` (Task 2), `app.db.get_database` (Task 1).
- Produces: `app.models.geofence.{Geofence, GeofenceCreate}`. Service functions in `app.services.geofences`: `create_geofence(db, data: GeofenceCreate) -> Geofence`, `get_geofence(db, geofence_id) -> Geofence`, `list_geofences(db) -> list[Geofence]`, `point_in_any_exclusive_zone(db, lon: float, lat: float) -> Geofence | None`. Exception: `GeofenceNotFound`. Router mounted at `/geofences`. `point_in_any_exclusive_zone` is the building block later plans (Pi mission core) use for CAP-2 exclusion-zone checks.

- [ ] **Step 1: Write the failing service-layer tests**

```python
# pathfinder-autonomous/backend/tests/test_geofence_service.py
import pytest

from app.models.geo import GeoPolygon
from app.models.geofence import GeofenceCreate
from app.services import geofences as geofence_service

FIELD_RING = [
    (-85.10, 38.00),
    (-85.10, 38.10),
    (-84.90, 38.10),
    (-84.90, 38.00),
    (-85.10, 38.00),
]


def test_create_and_get_geofence(db):
    created = geofence_service.create_geofence(
        db,
        GeofenceCreate(
            type="inclusive", name="Main field", boundary=GeoPolygon(coordinates=[FIELD_RING])
        ),
    )

    fetched = geofence_service.get_geofence(db, created.id)

    assert fetched.name == "Main field"
    assert fetched.type == "inclusive"


def test_get_geofence_not_found_raises(db):
    with pytest.raises(geofence_service.GeofenceNotFound):
        geofence_service.get_geofence(db, "000000000000000000000000")


def test_list_geofences_returns_all(db):
    geofence_service.create_geofence(
        db,
        GeofenceCreate(
            type="inclusive", name="Main field", boundary=GeoPolygon(coordinates=[FIELD_RING])
        ),
    )
    geofence_service.create_geofence(
        db,
        GeofenceCreate(
            type="exclusive", name="Pond", boundary=GeoPolygon(coordinates=[FIELD_RING])
        ),
    )

    fences = geofence_service.list_geofences(db)

    assert {f.name for f in fences} == {"Main field", "Pond"}
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_geofence_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.geofence'`

- [ ] **Step 3: Write the Geofence model**

```python
# pathfinder-autonomous/backend/app/models/geofence.py
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.geo import GeoPolygon


class Geofence(BaseModel):
    id: str = Field(alias="_id")
    type: Literal["inclusive", "exclusive"]
    boundary: GeoPolygon
    name: str
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}


class GeofenceCreate(BaseModel):
    type: Literal["inclusive", "exclusive"]
    boundary: GeoPolygon
    name: str
```

- [ ] **Step 4: Write the Geofence service**

```python
# pathfinder-autonomous/backend/app/services/geofences.py
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.database import Database

from app.models.geofence import Geofence, GeofenceCreate


class GeofenceNotFound(Exception):
    def __init__(self, geofence_id: str):
        self.geofence_id = geofence_id
        super().__init__(f"geofence {geofence_id} not found")


def _to_object_id(geofence_id: str) -> ObjectId:
    try:
        return ObjectId(geofence_id)
    except InvalidId as exc:
        raise GeofenceNotFound(geofence_id) from exc


def _doc_to_geofence(doc: dict) -> Geofence:
    doc = dict(doc)
    doc["_id"] = str(doc["_id"])
    return Geofence.model_validate(doc)


def create_geofence(db: Database, data: GeofenceCreate) -> Geofence:
    now = datetime.now(timezone.utc)
    doc = data.model_dump()
    doc["created_at"] = now
    doc["updated_at"] = now
    result = db.geofences.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _doc_to_geofence(doc)


def get_geofence(db: Database, geofence_id: str) -> Geofence:
    doc = db.geofences.find_one({"_id": _to_object_id(geofence_id)})
    if doc is None:
        raise GeofenceNotFound(geofence_id)
    return _doc_to_geofence(doc)


def list_geofences(db: Database) -> list[Geofence]:
    return [_doc_to_geofence(doc) for doc in db.geofences.find()]


def point_in_any_exclusive_zone(db: Database, lon: float, lat: float) -> Geofence | None:
    doc = db.geofences.find_one(
        {
            "type": "exclusive",
            "boundary": {
                "$geoIntersects": {
                    "$geometry": {"type": "Point", "coordinates": [lon, lat]}
                }
            },
        }
    )
    return _doc_to_geofence(doc) if doc else None
```

- [ ] **Step 5: Extend `ensure_indexes` with the 2dsphere index**

```python
# pathfinder-autonomous/backend/app/db.py
import os

from pymongo import ASCENDING, MongoClient
from pymongo.database import Database


def get_client() -> MongoClient:
    uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
    return MongoClient(uri)


def get_database(client: MongoClient | None = None) -> Database:
    client = client or get_client()
    db_name = os.environ.get("MONGO_DB_NAME", "papaya_pathfinder")
    return client[db_name]


def ensure_indexes(db: Database) -> None:
    db.rovers.create_index(
        [("status", ASCENDING)],
        unique=True,
        partialFilterExpression={"status": "active"},
        name="uniq_active_rover",
    )
    db.geofences.create_index([("boundary", "2dsphere")])
```

- [ ] **Step 6: Run the service tests and verify they pass**

Run: `pytest tests/test_geofence_service.py -v`
Expected: PASS (3 passed)

- [ ] **Step 7: Write the failing geospatial query test**

This is the test that a mocked Mongo could not validate correctly — it exercises the real 2dsphere index via `$geoIntersects`.

```python
# pathfinder-autonomous/backend/tests/test_geofence_geospatial.py
from app.models.geo import GeoPolygon
from app.models.geofence import GeofenceCreate
from app.services import geofences as geofence_service

POND_RING = [
    (-85.05, 38.04),
    (-85.05, 38.06),
    (-85.03, 38.06),
    (-85.03, 38.04),
    (-85.05, 38.04),
]


def test_point_inside_exclusive_zone_is_found(db):
    geofence_service.create_geofence(
        db,
        GeofenceCreate(type="exclusive", name="Pond", boundary=GeoPolygon(coordinates=[POND_RING])),
    )

    hit = geofence_service.point_in_any_exclusive_zone(db, lon=-85.04, lat=38.05)

    assert hit is not None
    assert hit.name == "Pond"


def test_point_outside_exclusive_zone_is_not_found(db):
    geofence_service.create_geofence(
        db,
        GeofenceCreate(type="exclusive", name="Pond", boundary=GeoPolygon(coordinates=[POND_RING])),
    )

    hit = geofence_service.point_in_any_exclusive_zone(db, lon=-84.50, lat=38.50)

    assert hit is None


def test_point_inside_inclusive_zone_is_ignored(db):
    # point_in_any_exclusive_zone only matches type="exclusive" fences
    geofence_service.create_geofence(
        db,
        GeofenceCreate(
            type="inclusive", name="Main field", boundary=GeoPolygon(coordinates=[POND_RING])
        ),
    )

    hit = geofence_service.point_in_any_exclusive_zone(db, lon=-85.04, lat=38.05)

    assert hit is None
```

- [ ] **Step 8: Run the geospatial tests and verify they pass**

Run: `pytest tests/test_geofence_geospatial.py -v`
Expected: PASS (3 passed). If this fails with an error mentioning `2dsphere` or `$geoIntersects`, verify `ensure_indexes` actually ran against this test's `db` fixture (it does, in `conftest.py`) and that whatever `MONGO_URI` points to (Atlas, or the local `papaya-dev-mongo` container from Task 1 Step 3) is a real MongoDB 7+ — geospatial query support requires a real index, which `ensure_indexes` just created.

- [ ] **Step 9: Write the Geofence router and register it**

```python
# pathfinder-autonomous/backend/app/routers/geofences.py
from fastapi import APIRouter, Depends, HTTPException
from pymongo.database import Database

from app.db import get_database
from app.models.geofence import Geofence, GeofenceCreate
from app.services import geofences as geofence_service

router = APIRouter(prefix="/geofences", tags=["geofences"])


@router.post("", response_model=Geofence, status_code=201)
def create_geofence(
    data: GeofenceCreate, db: Database = Depends(get_database)
) -> Geofence:
    return geofence_service.create_geofence(db, data)


@router.get("", response_model=list[Geofence])
def list_geofences(db: Database = Depends(get_database)) -> list[Geofence]:
    return geofence_service.list_geofences(db)


@router.get("/{geofence_id}", response_model=Geofence)
def get_geofence(geofence_id: str, db: Database = Depends(get_database)) -> Geofence:
    try:
        return geofence_service.get_geofence(db, geofence_id)
    except geofence_service.GeofenceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
```

```python
# pathfinder-autonomous/backend/app/main.py
from fastapi import FastAPI

from app.db import ensure_indexes, get_client, get_database
from app.routers import geofences, rovers

app = FastAPI(title="Papaya Pathfinder Backend")

app.include_router(rovers.router)
app.include_router(geofences.router)


@app.on_event("startup")
def on_startup() -> None:
    db = get_database(get_client())
    ensure_indexes(db)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 10: Run the full suite and verify everything passes**

Run: `pytest -v`
Expected: PASS (all tests from Tasks 1–4)

- [ ] **Step 11: Commit**

```bash
git add pathfinder-autonomous/backend
git commit -m "feat(backend): add geofence CRUD with 2dsphere exclusion-zone queries"
```

---

### Task 5: Command queue

**Files:**
- Create: `pathfinder-autonomous/backend/app/models/command.py`
- Create: `pathfinder-autonomous/backend/app/services/commands.py`
- Create: `pathfinder-autonomous/backend/app/routers/commands.py`
- Modify: `pathfinder-autonomous/backend/app/db.py` (extend `ensure_indexes`)
- Modify: `pathfinder-autonomous/backend/app/main.py` (register the commands router)
- Test: `pathfinder-autonomous/backend/tests/test_command_service.py`
- Test: `pathfinder-autonomous/backend/tests/test_command_router.py`

**Interfaces:**
- Consumes: `app.services.rovers.{get_rover, activate_rover, deactivate_rover, RoverNotFound, AnotherRoverActive}` (Task 3), `app.db.get_database` (Task 1).
- Produces: `app.models.command.{Command, CommandCreate, CommandType}` (`CommandType` is one of `"start_sweep" | "pause_sweep" | "resume_sweep" | "stop_sweep" | "abort_home" | "update_geofence"`). Service functions in `app.services.commands`: `enqueue_command(db, data: CommandCreate) -> Command`, `poll_commands(db, rover_id: str) -> list[Command]` (also marks returned commands `status="delivered"`), `ack_command(db, command_id: str) -> Command`. Exception: `CommandNotFound`. Router mounted at `/commands`: `POST /commands`, `GET /commands/poll/{rover_id}`, `POST /commands/{command_id}/ack`.

- [ ] **Step 1: Write the failing service-layer tests**

```python
# pathfinder-autonomous/backend/tests/test_command_service.py
import pytest

from app.models.command import CommandCreate
from app.models.rover import RoverCreate
from app.services import commands as command_service
from app.services import rovers as rover_service


def test_enqueue_and_poll_command(db):
    rover = rover_service.create_rover(db, RoverCreate(name="George"))

    enqueued = command_service.enqueue_command(
        db, CommandCreate(rover_id=rover.id, type="update_geofence", payload={"geofence_id": "abc"})
    )
    assert enqueued.status == "pending"

    polled = command_service.poll_commands(db, rover.id)

    assert len(polled) == 1
    assert polled[0].id == enqueued.id
    assert polled[0].status == "delivered"


def test_poll_only_returns_own_rovers_commands(db):
    rover_a = rover_service.create_rover(db, RoverCreate(name="George"))
    rover_b = rover_service.create_rover(db, RoverCreate(name="Rover2"))
    command_service.enqueue_command(
        db, CommandCreate(rover_id=rover_a.id, type="update_geofence", payload={})
    )

    polled_b = command_service.poll_commands(db, rover_b.id)

    assert polled_b == []


def test_poll_does_not_redeliver_already_delivered_commands(db):
    rover = rover_service.create_rover(db, RoverCreate(name="George"))
    command_service.enqueue_command(
        db, CommandCreate(rover_id=rover.id, type="update_geofence", payload={})
    )
    command_service.poll_commands(db, rover.id)

    second_poll = command_service.poll_commands(db, rover.id)

    assert second_poll == []


def test_ack_command_marks_it_acked(db):
    rover = rover_service.create_rover(db, RoverCreate(name="George"))
    enqueued = command_service.enqueue_command(
        db, CommandCreate(rover_id=rover.id, type="update_geofence", payload={})
    )

    acked = command_service.ack_command(db, enqueued.id)

    assert acked.status == "acked"
    assert acked.acked_at is not None


def test_ack_unknown_command_raises(db):
    with pytest.raises(command_service.CommandNotFound):
        command_service.ack_command(db, "000000000000000000000000")


def test_enqueue_command_for_unknown_rover_raises(db):
    with pytest.raises(rover_service.RoverNotFound):
        command_service.enqueue_command(
            db,
            CommandCreate(
                rover_id="000000000000000000000000", type="update_geofence", payload={}
            ),
        )


def test_start_sweep_activates_rover(db):
    rover = rover_service.create_rover(db, RoverCreate(name="George"))

    command_service.enqueue_command(
        db, CommandCreate(rover_id=rover.id, type="start_sweep", payload={})
    )

    assert rover_service.get_rover(db, rover.id).status == "active"


def test_start_sweep_rejected_while_another_rover_active(db):
    rover_a = rover_service.create_rover(db, RoverCreate(name="George"))
    rover_b = rover_service.create_rover(db, RoverCreate(name="Rover2"))
    command_service.enqueue_command(
        db, CommandCreate(rover_id=rover_a.id, type="start_sweep", payload={})
    )

    with pytest.raises(rover_service.AnotherRoverActive):
        command_service.enqueue_command(
            db, CommandCreate(rover_id=rover_b.id, type="start_sweep", payload={})
        )


def test_stop_sweep_deactivates_rover(db):
    rover = rover_service.create_rover(db, RoverCreate(name="George"))
    command_service.enqueue_command(
        db, CommandCreate(rover_id=rover.id, type="start_sweep", payload={})
    )

    command_service.enqueue_command(
        db, CommandCreate(rover_id=rover.id, type="stop_sweep", payload={})
    )

    assert rover_service.get_rover(db, rover.id).status == "inactive"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_command_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.command'`

- [ ] **Step 3: Write the Command model**

```python
# pathfinder-autonomous/backend/app/models/command.py
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

CommandType = Literal[
    "start_sweep",
    "pause_sweep",
    "resume_sweep",
    "stop_sweep",
    "abort_home",
    "update_geofence",
]


class Command(BaseModel):
    id: str = Field(alias="_id")
    rover_id: str
    type: CommandType
    payload: dict[str, Any] = Field(default_factory=dict)
    status: Literal["pending", "delivered", "acked"] = "pending"
    created_at: datetime
    delivered_at: datetime | None = None
    acked_at: datetime | None = None

    model_config = {"populate_by_name": True}


class CommandCreate(BaseModel):
    rover_id: str
    type: CommandType
    payload: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Write the Command service**

```python
# pathfinder-autonomous/backend/app/services/commands.py
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.database import Database

from app.models.command import Command, CommandCreate
from app.services import rovers as rover_service

_STOP_TYPES = {"pause_sweep", "stop_sweep", "abort_home"}


class CommandNotFound(Exception):
    def __init__(self, command_id: str):
        self.command_id = command_id
        super().__init__(f"command {command_id} not found")


def _to_object_id(command_id: str) -> ObjectId:
    try:
        return ObjectId(command_id)
    except InvalidId as exc:
        raise CommandNotFound(command_id) from exc


def _doc_to_command(doc: dict) -> Command:
    doc = dict(doc)
    doc["_id"] = str(doc["_id"])
    return Command.model_validate(doc)


def enqueue_command(db: Database, data: CommandCreate) -> Command:
    rover_service.get_rover(db, data.rover_id)  # raises RoverNotFound if missing

    if data.type == "start_sweep":
        rover_service.activate_rover(db, data.rover_id)  # raises AnotherRoverActive
    elif data.type in _STOP_TYPES:
        rover_service.deactivate_rover(db, data.rover_id)

    doc = data.model_dump()
    doc["status"] = "pending"
    doc["created_at"] = datetime.now(timezone.utc)
    doc["delivered_at"] = None
    doc["acked_at"] = None
    result = db.commands.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _doc_to_command(doc)


def poll_commands(db: Database, rover_id: str) -> list[Command]:
    now = datetime.now(timezone.utc)
    pending = list(
        db.commands.find({"rover_id": rover_id, "status": "pending"}).sort(
            "created_at", 1
        )
    )
    delivered = []
    for doc in pending:
        db.commands.update_one(
            {"_id": doc["_id"]}, {"$set": {"status": "delivered", "delivered_at": now}}
        )
        doc["status"] = "delivered"
        doc["delivered_at"] = now
        delivered.append(_doc_to_command(doc))
    return delivered


def ack_command(db: Database, command_id: str) -> Command:
    object_id = _to_object_id(command_id)
    now = datetime.now(timezone.utc)
    result = db.commands.update_one(
        {"_id": object_id}, {"$set": {"status": "acked", "acked_at": now}}
    )
    if result.matched_count == 0:
        raise CommandNotFound(command_id)
    doc = db.commands.find_one({"_id": object_id})
    return _doc_to_command(doc)
```

- [ ] **Step 5: Extend `ensure_indexes` with the command-queue index**

```python
# pathfinder-autonomous/backend/app/db.py
import os

from pymongo import ASCENDING, MongoClient
from pymongo.database import Database


def get_client() -> MongoClient:
    uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
    return MongoClient(uri)


def get_database(client: MongoClient | None = None) -> Database:
    client = client or get_client()
    db_name = os.environ.get("MONGO_DB_NAME", "papaya_pathfinder")
    return client[db_name]


def ensure_indexes(db: Database) -> None:
    db.rovers.create_index(
        [("status", ASCENDING)],
        unique=True,
        partialFilterExpression={"status": "active"},
        name="uniq_active_rover",
    )
    db.geofences.create_index([("boundary", "2dsphere")])
    db.commands.create_index([("rover_id", ASCENDING), ("status", ASCENDING)])
```

- [ ] **Step 6: Run the service tests and verify they pass**

Run: `pytest tests/test_command_service.py -v`
Expected: PASS (9 passed)

- [ ] **Step 7: Write the failing router-layer test**

```python
# pathfinder-autonomous/backend/tests/test_command_router.py
def test_enqueue_poll_ack_flow(client):
    rover_id = client.post("/rovers", json={"name": "George"}).json()["_id"]

    enqueue_response = client.post(
        "/commands", json={"rover_id": rover_id, "type": "update_geofence", "payload": {}}
    )
    assert enqueue_response.status_code == 201
    command_id = enqueue_response.json()["_id"]

    poll_response = client.get(f"/commands/poll/{rover_id}")
    assert poll_response.status_code == 200
    assert len(poll_response.json()) == 1
    assert poll_response.json()[0]["status"] == "delivered"

    ack_response = client.post(f"/commands/{command_id}/ack")
    assert ack_response.status_code == 200
    assert ack_response.json()["status"] == "acked"


def test_start_sweep_rejected_via_api_when_another_rover_active(client):
    rover_a_id = client.post("/rovers", json={"name": "George"}).json()["_id"]
    rover_b_id = client.post("/rovers", json={"name": "Rover2"}).json()["_id"]
    client.post("/commands", json={"rover_id": rover_a_id, "type": "start_sweep", "payload": {}})

    response = client.post(
        "/commands", json={"rover_id": rover_b_id, "type": "start_sweep", "payload": {}}
    )

    assert response.status_code == 409
```

- [ ] **Step 8: Run the router test and verify it fails**

Run: `pytest tests/test_command_router.py -v`
Expected: FAIL — `404 != 201` (no `/commands` route registered yet).

- [ ] **Step 9: Write the Command router and register it**

```python
# pathfinder-autonomous/backend/app/routers/commands.py
from fastapi import APIRouter, Depends, HTTPException
from pymongo.database import Database

from app.db import get_database
from app.models.command import Command, CommandCreate
from app.services import commands as command_service
from app.services import rovers as rover_service

router = APIRouter(prefix="/commands", tags=["commands"])


@router.post("", response_model=Command, status_code=201)
def enqueue_command(
    data: CommandCreate, db: Database = Depends(get_database)
) -> Command:
    try:
        return command_service.enqueue_command(db, data)
    except rover_service.RoverNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except rover_service.AnotherRoverActive as exc:
        raise HTTPException(
            status_code=409,
            detail=f"rover {exc.active_rover_id} already has an active mission",
        ) from exc


@router.get("/poll/{rover_id}", response_model=list[Command])
def poll_commands(rover_id: str, db: Database = Depends(get_database)) -> list[Command]:
    return command_service.poll_commands(db, rover_id)


@router.post("/{command_id}/ack", response_model=Command)
def ack_command(command_id: str, db: Database = Depends(get_database)) -> Command:
    try:
        return command_service.ack_command(db, command_id)
    except command_service.CommandNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
```

```python
# pathfinder-autonomous/backend/app/main.py
from fastapi import FastAPI

from app.db import ensure_indexes, get_client, get_database
from app.routers import commands, geofences, rovers

app = FastAPI(title="Papaya Pathfinder Backend")

app.include_router(rovers.router)
app.include_router(geofences.router)
app.include_router(commands.router)


@app.on_event("startup")
def on_startup() -> None:
    db = get_database(get_client())
    ensure_indexes(db)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 10: Run the full suite and verify everything passes**

Run: `pytest -v`
Expected: PASS (all tests from Tasks 1–5)

- [ ] **Step 11: Commit**

```bash
git add pathfinder-autonomous/backend
git commit -m "feat(backend): add polled command queue with rover-activation side effects"
```

---

### Task 6: End-to-end integration test and dev documentation

**Files:**
- Create: `pathfinder-autonomous/backend/tests/test_end_to_end_flow.py`
- Create: `pathfinder-autonomous/backend/README.md`

**Interfaces:**
- Consumes: everything from Tasks 1–5 (`client` fixture, all three routers).
- Produces: nothing new — this task proves the pieces work together as a whole and documents how to run the service, for whoever picks up the next plan (Pi mission core).

- [ ] **Step 1: Write the end-to-end test**

This walks the exact scenario the design spec describes: two rover prototypes registered, a geofence drawn, a mission started on one rover, blocked on the other, and a full command lifecycle.

```python
# pathfinder-autonomous/backend/tests/test_end_to_end_flow.py
def test_two_rover_fleet_mission_lifecycle(client):
    george = client.post(
        "/rovers", json={"name": "George", "supported_mission_packages": ["MP-1"]}
    ).json()
    prototype_b = client.post("/rovers", json={"name": "Prototype-B"}).json()

    field = client.post(
        "/geofences",
        json={
            "type": "inclusive",
            "name": "Main field",
            "boundary": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-85.10, 38.00],
                        [-85.10, 38.10],
                        [-84.90, 38.10],
                        [-84.90, 38.00],
                        [-85.10, 38.00],
                    ]
                ],
            },
        },
    ).json()

    start = client.post(
        "/commands",
        json={
            "rover_id": george["_id"],
            "type": "start_sweep",
            "payload": {"geofence_id": field["_id"]},
        },
    )
    assert start.status_code == 201

    blocked = client.post(
        "/commands", json={"rover_id": prototype_b["_id"], "type": "start_sweep", "payload": {}}
    )
    assert blocked.status_code == 409

    polled = client.get(f"/commands/poll/{george['_id']}").json()
    assert len(polled) == 1
    assert polled[0]["type"] == "start_sweep"

    client.post(f"/commands/{polled[0]['_id']}/ack")

    stop = client.post(
        "/commands", json={"rover_id": george["_id"], "type": "stop_sweep", "payload": {}}
    )
    assert stop.status_code == 201

    now_allowed = client.post(
        "/commands", json={"rover_id": prototype_b["_id"], "type": "start_sweep", "payload": {}}
    )
    assert now_allowed.status_code == 201
```

- [ ] **Step 2: Run it and verify it passes**

Run: `pytest tests/test_end_to_end_flow.py -v`
Expected: PASS — if it fails, re-check the individual Task 3–5 tests first; this test only combines already-tested behavior and shouldn't need new logic.

- [ ] **Step 3: Write the dev README**

```markdown
# Papaya Pathfinder — Backend

Local, container-hosted backend for MP-1: Rover fleet registry, Geofence
CRUD, and the polled command queue. Data lives in MongoDB Atlas (hosted
separately, not part of this compose file) — see
`docs/superpowers/specs/2026-09-24-mp1-map-detect-explore-design.md` for
the design this implements.

## Configure

    cp .env.example .env

Fill in `.env` with your MongoDB Atlas connection string (Atlas UI:
Database > Connect > Drivers). `.env` is gitignored — never commit real
credentials.

## Run it

    docker compose up --build

Backend on http://localhost:8000, health check at `/health`.

## Run the tests

Tests need *some* MongoDB instance to run against — either your Atlas
dev cluster (via `.env`'s `MONGO_URI`), or a disposable local container
so you're not burning Atlas Free Tier usage on every test run:

    docker run --rm -d -p 27017:27017 --name papaya-dev-mongo mongo:7

Then, with `MONGO_URI=mongodb://localhost:27017` in `.env` (or pointed
at Atlas):

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    pytest -v

Tests use a separate `papaya_pathfinder_test` database and drop it after
each run — do this against a dev cluster or the local container, not
your production Atlas cluster, since every test run creates and drops
that database on whatever instance `MONGO_URI` points to.

## API surface

- `POST/GET /rovers`, `GET/PATCH /rovers/{id}` — fleet registry
- `POST/GET /geofences`, `GET /geofences/{id}` — inclusive/exclusive boundaries
- `POST /commands` — enqueue (rejects `start_sweep` with 409 if another
  rover is already active)
- `GET /commands/poll/{rover_id}` — a rover polls this for its pending
  commands (marks them `delivered`)
- `POST /commands/{id}/ack` — rover acknowledges a delivered command
```

- [ ] **Step 4: Commit**

```bash
git add pathfinder-autonomous/backend
git commit -m "test(backend): add end-to-end fleet/geofence/command flow test and README"
```

---

## Self-Review Notes

- **Spec coverage:** GeoJSON + 2dsphere (Task 2, 4) ✓. Rover registry + one-active-rover invariant (Task 3) ✓. Geofence CRUD (Task 4) ✓. Command queue, poll model, `start_sweep`/stop-type rover activation side effects (Task 5) ✓. Obstacle records, telemetry, sensor-manifest UI, sync/reconciliation, ESP32 firmware, sweep-session/mission-flow state machine are explicitly out of scope for this plan — they belong to the Pi mission core, Pi telemetry + sync, and ESP32 firmware plans that follow.
- **Placeholder scan:** no TBD/TODO; every step has runnable code.
- **Type consistency:** `Rover.id`/`Geofence.id`/`Command.id` are all `str` (stringified `ObjectId`) consistently across models, services, and router response types; `RoverCreate`/`RoverUpdate`/`GeofenceCreate`/`CommandCreate` field names match what the corresponding service function reads via `.model_dump()` in every task.

