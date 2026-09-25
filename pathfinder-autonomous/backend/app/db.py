import os

from dotenv import load_dotenv
from fastapi import Depends
from pymongo import ASCENDING, MongoClient
from pymongo.database import Database

load_dotenv()


def get_client() -> MongoClient:
    uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
    return MongoClient(uri)


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
