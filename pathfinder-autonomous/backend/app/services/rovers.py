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
