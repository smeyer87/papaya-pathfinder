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
