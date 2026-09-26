from pymongo.database import Database

from app.models.obstacle import Obstacle

# Backend/human-owned review lifecycle. The Pi's own obstacle type
# (papaya_mission.obstacle.Obstacle) has none of these fields, so every inbound
# sync payload carries Pydantic's defaults for them -- "pending" and two Nones.
# They must therefore only ever be written on first insert.
_REVIEW_FIELDS = ("review_status", "reviewed_by", "reviewed_at")

# `status` is shared rather than cleanly Pi-owned. The Pi legitimately drives
# the "temporary" -> "permanent-pending" promotion as its confidence grows, so
# a re-sync has to be able to update it. But "permanent-confirmed" is a review
# outcome -- papaya_mission.obstacle.ObstacleStatus is only
# Literal["temporary", "permanent-pending"], so the Pi cannot even express it --
# and a re-sync must not downgrade a confirmed obstacle back to pending.
_REVIEW_TERMINAL_STATUS = "permanent-confirmed"


def sync_obstacles(db: Database, obstacles: list[Obstacle]) -> int:
    """Upsert obstacles from a Pi sync batch, preserving backend-owned review
    state.

    Deliberately NOT a `replace_one`: a full-document replace would overwrite a
    human's review decision with the defaults Pydantic filled in for the fields
    the Pi never sends, silently reverting a confirmed obstacle to pending on
    any routine retry or backlog flush.
    """
    count = 0
    for obstacle in obstacles:
        doc = obstacle.model_dump(by_alias=True)
        pi_owned = {
            key: value
            for key, value in doc.items()
            if key != "_id" and key != "status" and key not in _REVIEW_FIELDS
        }
        review_defaults = {key: doc[key] for key in _REVIEW_FIELDS}
        db.obstacles.update_one(
            {"_id": doc["_id"]},
            # $setOnInsert seeds the review lifecycle on first detection only,
            # so a later sync of the same obstacle leaves it untouched. `status`
            # rides along here so a brand-new obstacle still lands with the
            # status the Pi reported.
            {"$set": pi_owned, "$setOnInsert": {**review_defaults, "status": doc["status"]}},
            upsert=True,
        )
        # Apply the Pi's status only where it is the Pi's to apply -- i.e. as
        # long as a review has not already confirmed this obstacle. Kept as a
        # separate filtered update because a plain $set cannot be conditional;
        # the filter makes it a no-op on an already-confirmed record regardless
        # of ordering against a concurrent review.
        db.obstacles.update_one(
            {"_id": doc["_id"], "status": {"$ne": _REVIEW_TERMINAL_STATUS}},
            {"$set": {"status": doc["status"]}},
        )
        count += 1
    return count


def list_pending_review(db: Database) -> list[Obstacle]:
    docs = db.obstacles.find({"status": "permanent-pending", "review_status": "pending"})
    return [Obstacle.model_validate(doc) for doc in docs]
