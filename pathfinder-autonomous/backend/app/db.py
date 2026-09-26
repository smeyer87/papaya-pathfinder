import os

from dotenv import load_dotenv
from fastapi import Depends
from pymongo import ASCENDING, MongoClient
from pymongo.database import Database

load_dotenv()


_client: MongoClient | None = None


def get_client() -> MongoClient:
    """Return the process-wide MongoClient.

    MongoClient is itself a connection pool and is designed to be created once
    and shared. Building one per request would mean a fresh DNS/TLS handshake
    and a fresh pool on every HTTP call, none of which ever get closed.

    MONGO_URI is required -- no fallback to a local mongod, so a missing .env
    fails loudly instead of silently pointing at the wrong database.

    tz_aware=True because BSON stores datetimes as UTC milliseconds with no
    zone, and pymongo's default is to hand them back timezone-NAIVE. Every
    datetime this service stores is UTC (Pi-supplied timestamps like an
    obstacle's first_detected_at, and backend-set ones like Rover.created_at),
    so a naive read-back silently drops that fact: FastAPI then serialises it
    without a Z/offset and a UI is free to read it as local time. Setting it on
    the client makes it uniform for every collection and every caller, rather
    than something each read site has to remember.
    """
    global _client
    if _client is None:
        _client = MongoClient(os.environ["MONGO_URI"], tz_aware=True)
    return _client


def get_database(client: MongoClient = Depends(get_client)) -> Database:
    db_name = os.environ.get("MONGO_DB_NAME", "papaya_pathfinder")
    return client[db_name]


def _ensure_telemetry_timeseries_collection(db: Database) -> None:
    if "telemetry" not in db.list_collection_names():
        db.create_collection(
            "telemetry",
            timeseries={"timeField": "timestamp", "metaField": "rover_id", "granularity": "seconds"},
        )


def ensure_indexes(db: Database) -> None:
    """Create/verify all indexes this service depends on.

    Extended in later tasks (geofences' 2dsphere index).
    """
    db.rovers.create_index(
        [("status", ASCENDING)],
        unique=True,
        partialFilterExpression={"status": "active"},
        name="uniq_active_rover",
    )
    db.geofences.create_index([("boundary", "2dsphere")])
    db.commands.create_index([("rover_id", ASCENDING), ("status", ASCENDING)])
    db.sweep_sessions.create_index([("rover_id", ASCENDING)])
    db.obstacles.create_index([("position", "2dsphere")])
    _ensure_telemetry_timeseries_collection(db)
    db.telemetry.create_index([("_id", ASCENDING)])
