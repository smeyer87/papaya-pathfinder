from pymongo.database import Database
from pymongo.errors import BulkWriteError

from app.models.telemetry import TelemetryRecord

_DUPLICATE_KEY_ERROR_CODE = 11000


def sync_telemetry(db: Database, records: list[TelemetryRecord]) -> int:
    """Telemetry is append-only -- insert, not upsert. Client-generated IDs
    make retries safe.

    NOTE: MongoDB time-series collections do not support unique indexes --
    not even on `_id` (server rejects `create_index(..., unique=True)` with
    "Unique indexes are not supported on time-series collections", code 72).
    So a duplicate `_id` insert does NOT raise a duplicate-key error here the
    way it would on a normal collection -- it silently succeeds and creates a
    second copy. That means BulkWriteError/code-11000 can never actually
    fire against this collection, so idempotency has to be enforced at the
    application layer instead: check which ids are already synced first, and
    only insert the ones that are genuinely new. Any error encountered while
    checking or inserting (i.e. anything other than "it's already there")
    still propagates.
    """
    if not records:
        return 0

    docs = [record.model_dump(by_alias=True) for record in records]
    incoming_ids = [doc["_id"] for doc in docs]
    already_synced_ids = {
        existing["_id"]
        for existing in db.telemetry.find({"_id": {"$in": incoming_ids}}, {"_id": 1})
    }
    seen_ids: set = set()
    new_docs = []
    for doc in docs:
        doc_id = doc["_id"]
        if doc_id in already_synced_ids or doc_id in seen_ids:
            continue
        seen_ids.add(doc_id)
        new_docs.append(doc)
    if not new_docs:
        return 0

    try:
        result = db.telemetry.insert_many(new_docs, ordered=False)
        return len(result.inserted_ids)
    except BulkWriteError as exc:
        write_errors = exc.details.get("writeErrors", [])
        real_errors = [e for e in write_errors if e.get("code") != _DUPLICATE_KEY_ERROR_CODE]
        if real_errors:
            raise
        return len(new_docs) - len(write_errors)
