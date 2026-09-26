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
    """
    global _client
    if _client is None:
        _client = MongoClient(os.environ["MONGO_URI"])
    return _client


def get_database(client: MongoClient = Depends(get_client)) -> Database:
    db_name = os.environ.get("MONGO_DB_NAME", "papaya_pathfinder")
    return client[db_name]


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
