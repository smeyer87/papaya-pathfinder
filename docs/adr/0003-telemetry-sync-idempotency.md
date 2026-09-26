# ADR 0003: Telemetry sync idempotency is enforced at the application layer, not the database

## Status

Accepted — 2026-09-25

## Context

The MP-1 Backend Obstacle & Telemetry Sync plan
(`docs/superpowers/plans/2026-09-24-mp1-backend-obstacle-telemetry-sync.md`)
specified that `sync_telemetry` should be idempotent on retry via MongoDB's
duplicate-key error (code 11000) on a repeated client-generated `_id`,
backed by a unique index.

During implementation this turned out to be impossible: MongoDB (verified
against the live cluster, server 8.0.32) categorically rejects unique
indexes on time-series collections —
`db.telemetry.create_index([("_id", ASCENDING)], unique=True)` raises
`OperationFailure` code 72, "Unique indexes are not supported on
time-series collections." A control test confirmed the identical
duplicate-key mechanism works as expected on a normal (non-time-series)
collection on the same cluster, ruling out a driver or configuration
issue — the restriction is specific to time-series collections. Without a
unique index, a duplicate `_id` insert into a time-series collection does
not raise an error at all; it silently succeeds and creates a second
document sharing that `_id`.

## Decision

Keep the telemetry collection as a time-series collection, per the design
spec's already-decided architecture for telemetry storage and query
efficiency at the expected data volume.

Replace the database-enforced uniqueness guarantee with an
application-level check, implemented in
`pathfinder-autonomous/backend/app/services/telemetry.py`:
`sync_telemetry` queries which `_id`s in the incoming batch already exist
in the collection before inserting, and inserts only the ones that are
genuinely new — deduplicating both against the database and within the
batch itself, since a single sync call can otherwise contain the same
`_id` more than once. A non-unique index on `_id`
(`pathfinder-autonomous/backend/app/db.py`, `ensure_indexes()`) is
permitted on time-series collections and keeps this existing-id check an
index scan (`IXSCAN`) rather than a full collection scan (`COLLSCAN`) on
every sync call.

This is judged safe for this project's actual architecture: exactly one
Pi syncs its own telemetry, sequentially, retrying after a dropped
connection rather than writing concurrently from multiple sources. There
is no concurrent-writer path to the same `_id` in the current or planned
system.

## Consequences

- The idempotency guarantee is now best-effort and application-enforced
  rather than database-enforced. A future architecture change introducing
  concurrent writers to the same telemetry `_id` (unlikely, but worth
  naming here) would need to revisit this decision.
- The existing-id check adds one query per sync call, mitigated by the
  non-unique `_id` index.
- If a future MongoDB server version adds unique-index support for
  time-series collections, the check-based approach could be simplified
  back to relying on a duplicate-key error — there is no urgency to do so.
