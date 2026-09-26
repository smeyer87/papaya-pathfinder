from fastapi import APIRouter, Depends
from pydantic import BaseModel
from pymongo.database import Database

from app.db import get_database
from app.models.obstacle import ObstacleSyncBatch
from app.models.sweep_session import SweepSessionSyncBatch
from app.models.telemetry import TelemetrySyncBatch
from app.services import obstacles as obstacle_service
from app.services import sweep_sessions as sweep_session_service
from app.services import telemetry as telemetry_service

router = APIRouter(prefix="/sync", tags=["sync"])


class SyncResult(BaseModel):
    """Response shape shared by every sync endpoint.

    A single `synced` count was ambiguous across the three endpoints: for the
    upsert-based ones it meant "records processed" (always the whole batch),
    while for telemetry it meant "records genuinely newly inserted" (0 on a
    full retry). A client checking `synced == len(batch)` to decide whether a
    batch got through therefore worked on two endpoints and never terminated
    on the third.

    Splitting the two meanings makes the check unambiguous:

    - `received` -- how many records the endpoint accepted and processed.
      Always the batch size, on every endpoint, first send or retry.
    - `inserted` -- how many records were actually written. For the
      upsert-based endpoints this equals `received`, since every record is
      inserted or updated. For telemetry (append-only, deduplicated against
      already-synced ids) it can be less, and is 0 on a full retry.
    """

    received: int
    inserted: int


@router.post("/sweep-sessions")
def sync_sweep_sessions(
    batch: SweepSessionSyncBatch, db: Database = Depends(get_database)
) -> SyncResult:
    count = sweep_session_service.sync_sweep_sessions(db, batch.sessions)
    return SyncResult(received=len(batch.sessions), inserted=count)


@router.post("/obstacles")
def sync_obstacles(batch: ObstacleSyncBatch, db: Database = Depends(get_database)) -> SyncResult:
    count = obstacle_service.sync_obstacles(db, batch.obstacles)
    return SyncResult(received=len(batch.obstacles), inserted=count)


@router.post("/telemetry")
def sync_telemetry(batch: TelemetrySyncBatch, db: Database = Depends(get_database)) -> SyncResult:
    count = telemetry_service.sync_telemetry(db, batch.records)
    return SyncResult(received=len(batch.records), inserted=count)
