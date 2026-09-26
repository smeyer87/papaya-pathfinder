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
