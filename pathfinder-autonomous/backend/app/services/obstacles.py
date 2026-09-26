from pymongo.database import Database

from app.models.obstacle import Obstacle


def sync_obstacles(db: Database, obstacles: list[Obstacle]) -> int:
    count = 0
    for obstacle in obstacles:
        doc = obstacle.model_dump(by_alias=True)
        db.obstacles.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        count += 1
    return count


def list_pending_review(db: Database) -> list[Obstacle]:
    docs = db.obstacles.find({"status": "permanent-pending", "review_status": "pending"})
    return [Obstacle.model_validate(doc) for doc in docs]
