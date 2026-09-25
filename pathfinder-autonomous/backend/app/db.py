import os

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.database import Database

load_dotenv()


def get_client() -> MongoClient:
    uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
    return MongoClient(uri)


def get_database(client: MongoClient | None = None) -> Database:
    client = client or get_client()
    db_name = os.environ.get("MONGO_DB_NAME", "papaya_pathfinder")
    return client[db_name]


def ensure_indexes(db: Database) -> None:
    """Create/verify all indexes this service depends on.

    Extended in later tasks (rovers' one-active partial unique index,
    geofences' 2dsphere index). Empty for now -- no collections defined yet.
    """
    pass
