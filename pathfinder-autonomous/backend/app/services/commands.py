from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.database import Database

from app.models.command import Command, CommandCreate
from app.services import geofences as geofence_service
from app.services import rovers as rover_service

# Types that claim the one-active-rover lock. resume_sweep re-asserts it so that
# a rover cannot resume into a fleet where something else started driving.
_START_TYPES = {"start_sweep", "resume_sweep"}

# Types that release the lock. pause_sweep is deliberately NOT here: a paused
# mission still owns the rover.
_STOP_TYPES = {"stop_sweep", "abort_home"}

# Types whose payload may carry a geofence_id that must refer to a real geofence.
_GEOFENCE_PAYLOAD_TYPES = {"start_sweep", "update_geofence"}


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

    if data.type in _GEOFENCE_PAYLOAD_TYPES:
        geofence_id = data.payload.get("geofence_id")
        if geofence_id is not None:
            # raises GeofenceNotFound; done before any rover state changes
            geofence_service.get_geofence(db, geofence_id)

    if data.type in _START_TYPES:
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
