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
