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
