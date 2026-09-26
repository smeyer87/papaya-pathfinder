from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from pymongo.collection import Collection
from pymongo.errors import BulkWriteError

from app.models.telemetry import TelemetryRecord
from app.services import telemetry as telemetry_service

TIMESTAMP = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


def _record(record_id="tel-uuid-1", sequence_number=1):
    return TelemetryRecord(
        _id=record_id,
        rover_id="rover-uuid-1",
        timestamp=TIMESTAMP,
        local_tz_offset_minutes=-300,
        sweep_session_id="sess-uuid-1",
        sequence_number=sequence_number,
        metrics={"battery_voltage": 11.8},
    )


def test_sync_telemetry_inserts_new_records(db):
    count = telemetry_service.sync_telemetry(db, [_record()])

    assert count == 1
    stored = db.telemetry.find_one({"_id": "tel-uuid-1"})
    assert stored is not None
    assert stored["metrics"]["battery_voltage"] == 11.8


def test_sync_telemetry_is_idempotent_on_retry(db):
    telemetry_service.sync_telemetry(db, [_record()])

    # Simulate a retried sync after a dropped connection -- same batch
    # resent. Should not raise, and should not duplicate.
    count = telemetry_service.sync_telemetry(db, [_record()])

    assert count == 0  # nothing NEW was inserted this time
    assert db.telemetry.count_documents({}) == 1


def test_sync_telemetry_partial_retry_only_inserts_new_records(db):
    telemetry_service.sync_telemetry(db, [_record(record_id="tel-uuid-1")])

    # Second batch has one already-synced record and one genuinely new one.
    count = telemetry_service.sync_telemetry(
        db,
        [_record(record_id="tel-uuid-1"), _record(record_id="tel-uuid-2", sequence_number=2)],
    )

    assert count == 1
    assert db.telemetry.count_documents({}) == 2


def test_sync_telemetry_handles_empty_batch(db):
    count = telemetry_service.sync_telemetry(db, [])

    assert count == 0


def test_sync_telemetry_deduplicates_within_the_same_batch(db):
    count = telemetry_service.sync_telemetry(
        db,
        [
            _record(record_id="dup-uuid"),
            _record(record_id="dup-uuid", sequence_number=2),
        ],
    )

    assert count == 1
    assert db.telemetry.count_documents({"_id": "dup-uuid"}) == 1


def test_sync_telemetry_propagates_a_write_concern_failure(db):
    """A write-concern-only BulkWriteError means the documents were NOT
    durably written (e.g. an Atlas primary stepdown mid-insert). It must
    propagate, not be reported as a successful sync.

    Mocking is deliberate and confined to this one test: a real
    write-concern error cannot be triggered on demand against a live
    cluster, and the thing under test is the error PATH, not a query.
    """
    write_concern_failure = BulkWriteError(
        {
            "writeErrors": [],
            "writeConcernErrors": [
                {"code": 64, "errmsg": "waiting for replication timed out"}
            ],
            "nInserted": 0,
        }
    )

    with patch.object(Collection, "insert_many", side_effect=write_concern_failure):
        with pytest.raises(BulkWriteError):
            telemetry_service.sync_telemetry(db, [_record()])

    assert db.telemetry.count_documents({}) == 0
