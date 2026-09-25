from fastapi import APIRouter, Depends, HTTPException
from pymongo.database import Database
from pymongo.errors import WriteError

from app.db import get_database
from app.models.geofence import Geofence, GeofenceCreate
from app.services import geofences as geofence_service

router = APIRouter(prefix="/geofences", tags=["geofences"])


@router.post("", response_model=Geofence, status_code=201)
def create_geofence(
    data: GeofenceCreate, db: Database = Depends(get_database)
) -> Geofence:
    try:
        return geofence_service.create_geofence(db, data)
    except WriteError as exc:
        # The 2dsphere index validates geometry at insert time and rejects rings
        # that pydantic cannot see are bad (e.g. self-intersecting "bowties").
        # That is a bad request, not a server fault.
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[Geofence])
def list_geofences(db: Database = Depends(get_database)) -> list[Geofence]:
    return geofence_service.list_geofences(db)


@router.get("/{geofence_id}", response_model=Geofence)
def get_geofence(geofence_id: str, db: Database = Depends(get_database)) -> Geofence:
    try:
        return geofence_service.get_geofence(db, geofence_id)
    except geofence_service.GeofenceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
