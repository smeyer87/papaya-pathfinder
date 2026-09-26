from pymongo.database import Database

from app.models.sweep_session import SweepSession


def sync_sweep_sessions(db: Database, sessions: list[SweepSession]) -> int:
    count = 0
    for session in sessions:
        doc = session.model_dump(by_alias=True)
        db.sweep_sessions.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        count += 1
    return count
