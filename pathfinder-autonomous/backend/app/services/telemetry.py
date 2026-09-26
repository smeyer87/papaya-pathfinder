from pymongo.database import Database

from app.models.telemetry import TelemetryRecord


def sync_telemetry(db: Database, records: list[TelemetryRecord]) -> int:
    """Telemetry is append-only -- insert, not upsert. Client-generated IDs
    make retries safe.

    NOTE: MongoDB time-series collections do not support unique indexes --
    not even on `_id` (server rejects `create_index(..., unique=True)` with
    "Unique indexes are not supported on time-series collections", code 72).
    So a duplicate `_id` insert does NOT raise a duplicate-key error here the
    way it would on a normal collection -- it silently succeeds and creates a
    second copy. That means idempotency has to be enforced at the application
    layer instead: check which ids are already synced first, and only insert
    the ones that are genuinely new (see ADR 0003).

    Because that check runs BEFORE the insert, `insert_many` is only ever
    handed genuinely new documents -- a duplicate key is not a reachable
    outcome here. Every error out of `insert_many` therefore propagates
    untouched, including a write-concern failure (e.g. an Atlas primary
    stepdown mid-insert), which pymongo surfaces as a `BulkWriteError`
    carrying `writeConcernErrors` and an empty `writeErrors`. Nothing at
    this layer is treated as "fine": if the caller gets a count back, those
    records were durably written.
    """
    if not records:
        return 0

    docs = [record.model_dump(by_alias=True) for record in records]
    incoming_ids = [doc["_id"] for doc in docs]
    # The `_id` index on a time-series collection is built over each bucket's
    # min/max `_id` range, not over individual documents, and random UUIDs
    # spread across the whole id space with no correlation to which bucket a
    # record landed in -- so an `_id`-only filter cannot prune buckets and
    # ends up examining every one of them. Adding the collection's metaField
    # (`rover_id`) and a bound on its timeField (`timestamp`), both taken from
    # the incoming batch itself, lets the bucket index narrow the search to the
    # buckets that could actually hold these records. Same matched documents,
    # far less scanned. Correct for a batch spanning several rovers too, since
    # both clauses are derived from the batch rather than assumed.
    rover_ids = {doc["rover_id"] for doc in docs}
    timestamps = [doc["timestamp"] for doc in docs]
    already_synced_ids = {
        existing["_id"]
        for existing in db.telemetry.find(
            {
                "_id": {"$in": incoming_ids},
                "rover_id": {"$in": list(rover_ids)},
                "timestamp": {"$gte": min(timestamps), "$lte": max(timestamps)},
            },
            {"_id": 1},
        )
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

    result = db.telemetry.insert_many(new_docs, ordered=False)
    return len(result.inserted_ids)
