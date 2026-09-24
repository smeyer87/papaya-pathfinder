# MP-1: Map and Detect / Explore — Design

**Status:** Approved, ready for implementation planning
**Date:** 2026-09-24
**Mission package:** [MP-1](../../phase2/inputs/01-missions.md) (Map and Detect / Explore)
**Baseline:** [Phase 1 current state](2026-08-16-phase1-current-state.md)

## Why this spec exists

Phase 2 as scoped in [`docs/phase2/inputs/`](../../phase2/inputs/) is four
mission packages, each touching nearly every capability, sensor, and
platform decision. That's too large for one spec. MP-1 goes first — it's
Must priority, sequenced first ([D-2](../../phase2/inputs/05-assumptions-decisions.md)),
and every later mission depends on the map it produces.

Several decisions made here are **Phase 2-wide architecture**, not
MP-1-specific, and later mission specs (MP-2/3/4) should build on them
rather than re-litigate:

- Hybrid compute: Raspberry Pi 5 + existing ESP32-S3 (resolves [Q-1](../../phase2/inputs/05-assumptions-decisions.md))
- GPS-only positioning, no wheel encoders/IMU for now
- Store-and-forward data sync, checkpointed on every Home return
- Two-tier telemetry (live summary + bulk detailed log)
- Local, container-hosted Management UI reading from MongoDB

This spec supersedes the corresponding `TBD`/open items in
`docs/phase2/inputs/02-05` for MP-1's scope. Those input files should be
updated to reflect the decisions below once this spec is approved.

## Scenario

Operating within a geofence, the rover sweeps the enclosed area, maps
it, and tags obstacles it encounters as permanent (barrel, utility pole,
fence post — likely to persist across runs) or temporary (chairs,
vehicles — likely to change), building a reusable map that other
missions read from and append to.

- **Priority:** Must
- **Autonomy level:** Guided waypoint sweep — the rover does not choose
  its own path through unexplored area; it follows an auto-generated
  coverage pattern.

## Architecture

**Compute split.** Raspberry Pi 5 (mission logic, mapping, obstacle
classification, UI backend comms) paired with the existing ESP32-S3
(real-time drive/servo/ELRS, unchanged — [CON-B1–B6](../../phase2/inputs/05-assumptions-decisions.md)).
Pi and ESP32 communicate over a local link (UART or USB — exact choice
is an implementation-planning detail); the ESP32's manual-override
behavior is untouched.

**Positioning.** GPS-only ([SEN-6](../../phase2/inputs/03-sensors-compute-electronics.md),
~decimeter accuracy target). No wheel encoders or IMU for Phase 2 MP-1
— position between fixes is "last known GPS fix."

**Sensing.** Mast-mounted ultrasonic ([SEN-1](../../phase2/inputs/03-sensors-compute-electronics.md),
bearing + range) and the Pi AI Camera ([SEN-3](../../phase2/inputs/03-sensors-compute-electronics.md),
type classification) for obstacle detection. Bump sensors ([SEN-4](../../phase2/inputs/03-sensors-compute-electronics.md))
as a last-resort contact trigger. No LiDAR in this mission package.

**Mast.** Before committing to a custom design, evaluate reusing the
4tronix M.A.R.S. Rover mast — it already integrates ultrasonic, a
camera-class sensor, and a small rotation servo. Confirm height and
load-capacity specs are sufficient before ruling in or out; fall back to
a custom mast ([PLT-2](../../phase2/inputs/04-physical-platform.md)) if
they aren't.

**Data persistence.** MongoDB is the permanent, authoritative store —
not an archive. The rover works entirely from local storage during a
mission (store-and-forward) and syncs only at Home-return checkpoints,
even under continuous WiFi coverage, to avoid spending battery on
mid-mission transmission. The Management UI reads from MongoDB, never
directly from the rover, and assumes internet access at its hosting
point.

**UI hosting.** Local, container-hosted Management UI + backend
([CAP-1](../../phase2/inputs/02-capabilities.md)) on a home-network
host — no cloud hosting cost for the UI process itself, works
offline for local operations, and matches the store-and-forward pattern.

**Wiring/PCB impact.** New UART/USB link to the Pi, AI camera ribbon,
ultrasonic mast wiring, and a GPS module very likely force the PCB
respin already flagged in [CON-B4](../../phase2/inputs/05-assumptions-decisions.md),
plus the larger payload bay ([PLT-5](../../phase2/inputs/04-physical-platform.md))
needed to physically fit the Pi.

## Mission Flow

**Pre-mission setup.** Given the geofence polygon (drawn in the UI,
[CAP-2](../../phase2/inputs/02-capabilities.md)), auto-generate a
lawnmower-style coverage pattern of waypoints, routed to avoid any
exclusion zones inside the fence. A resumed mission starts from its
saved coverage checkpoint instead of regenerating from scratch.

**Execution loop.** The rover drives waypoint-to-waypoint on GPS-only
positioning. While moving, ultrasonic and the AI camera continuously
scan for obstacles:

- **Detection.** Tag the obstacle with position (GPS fix + bearing/
  range), a camera-classified type, and a permanent/temporary flag from
  a type heuristic (barrel/post/fence-type → permanent-candidate;
  chair/vehicle-type → temporary). Temporary tags go straight into the
  local obstacle list. Permanent-candidates are stored the same way but
  marked "pending review" — not treated as confirmed until a human
  confirms via the UI, post-sync ([CAP-3](../../phase2/inputs/02-capabilities.md)).
- **Bump contact.** Immediate stop, back off ([CAP-9](../../phase2/inputs/02-capabilities.md)),
  log an obstacle at the contact point with a low-confidence
  "contact-only" type, flagged for review.
- **GPS loss/degradation.** Continue on last-known heading for a short
  grace period; stop and send a high-priority alert if it doesn't
  reacquire.
- **Exclusion-zone intrusion** (e.g. from GPS drift). Stop and alert,
  per [CAP-2](../../phase2/inputs/02-capabilities.md)'s existing rule:
  under one rover-length and easily reversible → auto-reverse,
  otherwise wait for help.

**Interruption.** A Bingo Fuel trigger ([CAP-11](../../phase2/inputs/02-capabilities.md)/[D-4](../../phase2/inputs/05-assumptions-decisions.md))
or a manual stop pauses the sweep. Coverage progress is saved locally
and the rover heads home. The mission is marked incomplete/resumable,
not failed.

**Resume validation.** Transiting from the restart point back to the
saved resume point, the rover passively re-scans obstacles it passes.
Temporary obstacles no longer present are updated/cleared automatically.
Permanent-candidates that appear missing are *not* silently removed —
flagged as a discrepancy for human review, consistent with CAP-3. This
is a pass-by check, not a re-sweep of already-covered ground.

**Completion & sync.** Every Home return is a sync checkpoint — whether
from full completion or an interruption. On an interrupted run, the
rover uploads whatever partial data it collected as soon as it's home
with WiFi, rather than waiting for the eventual resume-and-complete.
Resuming later only needs to sync the incremental data gathered on that
leg (plus any resume-validation updates), supplementing the partial set
already in MongoDB.

## Data Model

**Geofence.** `id`, `type` (inclusive/exclusive), `vertices` (ordered
lat/long list), `name`, `created_at`/`updated_at`. One inclusive fence
plus zero or more exclusive fences define MP-1's operating area. Source
of truth is MongoDB; the rover keeps a local cached copy for offline
operation. Sector segmentation ([CAP-3](../../phase2/inputs/02-capabilities.md))
is deferred — v1 treats the whole geofenced area as a single unit.

**Sweep session** (enables resume). `id`, `geofence_id`, `status`
(in_progress / interrupted / completed), `pattern` (the generated
waypoint list), `last_completed_waypoint_index`, `started_at`,
`interrupted_at`, `completed_at`. Interruption persists this record
locally with `status=interrupted` and the progress marker; resume looks
it up and continues from `last_completed_waypoint_index + 1`.

**Obstacle record.** `id`, `sweep_session_id`, `position` (GPS lat/long,
+ raw bearing/range), `type` (camera classification label),
`classification_confidence`, `detection_method` (ultrasonic+camera /
contact-only), `status` (temporary / permanent-pending /
permanent-confirmed), `first_detected_at`, `last_confirmed_at` (updated
by resume-validation), `review_status` (pending / confirmed / rejected),
`reviewed_by`, `reviewed_at`, `synced_at` (null until pushed to Mongo).

**Local vs. Mongo storage.** The rover keeps a local embedded store
(e.g. SQLite on the Pi) as the working copy during a mission. MongoDB
mirrors the same schema as the authoritative store. Sync: at each
Home-return checkpoint, push local records where `synced_at IS NULL`,
then stamp them — which gives the "upload partial data now, supplement
incrementally on resume" behavior without separate interrupted-vs-
completed logic.

## Telemetry

Added as a v1 requirement to support troubleshooting and behavior
tracing, extending [CAP-4](../../phase2/inputs/02-capabilities.md) with
a concrete model.

**Record shape.** Fixed envelope (`rover_id`, `timestamp` UTC +
`local_tz_offset`, `sweep_session_id`, `sequence_number`) wrapping a
flexible `metrics` key-value map — e.g. `{"gps_lat": ..., "gps_fix_quality":
..., "battery_voltage": ..., "wifi_rssi": ..., "nav_mode": "sweep",
"waypoint_index": 5, ...}`. New metric keys (cell-level voltage once
[PWR-1](../../phase2/inputs/03-sensors-compute-electronics.md) lands,
temperature once a sensor exists, etc.) just appear in the map — no
schema change or migration. MP-1 populates only the fields its actual
hardware supports (GPS, pack-level battery, motor/servo status, WiFi
signal, nav status, mission status, error/event log); fields with no
sensor behind them yet are simply absent, not null placeholders.

**Two tiers.**
- **Live summary** — low-rate (position, battery, nav mode,
  errors/alerts), streamed continuously over whatever comms are up
  (LoRa/WiFi, per [CAP-5](../../phase2/inputs/02-capabilities.md)'s
  hybrid plan), for real-time operator visibility and alerting.
- **Detailed log** — full metrics map, sampled at an activity-dependent
  rate (~1s while driving, ~5s or slower while idle/stationary), stored
  locally, bulk-uploaded at each Home-return checkpoint alongside the
  obstacle data.

**Mongo storage.** Native MongoDB time-series collections for the
detailed log — built-in bucketing/compression, no hand-rolled bucket
documents, supported by both Atlas and Azure Cosmos DB for MongoDB.

## Testing / Acceptance Criteria

Every category below needs both a happy-path case and a deliberate
negative/failure-injection case — the design isn't validated until it's
been broken on purpose and shown to fail safely.

**Core sweep (happy path).** On a real geofenced test field: pattern
generation correctly avoids exclusion zones; the rover completes a full
sweep in one uninterrupted run; encountered obstacles are correctly
tagged; after the Home-return checkpoint, the obstacle list and
telemetry log both appear correctly in MongoDB and the UI; a reviewer
can confirm/reject permanent-candidates and see it reflected in Mongo.

**Interruption + resume (happy path).** Trigger a simulated
interruption mid-sweep. Verify: the rover returns home; partial data
uploads at that Home-return; the sweep-session record shows
`status=interrupted` with the correct progress marker. Resume and
verify: the rover goes directly to the saved resume point; performs
resume-validation scans, correctly updating stale temporary obstacles
and flagging (not removing) missing permanent-candidates; completes the
remaining pattern; the final Home-return uploads only the incremental
data. Total Mongo records should match a full uninterrupted run — no
duplicates, no gaps.

**Safety behaviors (happy path + negative).**
- GPS loss/degradation → continues briefly on last heading, then stops
  and alerts if not reacquired. **Negative test needs a debug hook** to
  force a "no fix"/degraded-fix state on demand — testing this only
  when GPS happens to actually drop isn't repeatable.
- Exclusion-zone intrusion → stop + alert, correct
  auto-reverse-vs-wait-for-help behavior at the one-rover-length
  threshold.
- Bump-sensor contact → immediate stop, back-off, flagged "contact-only"
  obstacle logged. **Negative test needs a debug hook** to force a
  synthetic bump event on the ESP32 — physically staging a collision on
  every test run isn't practical.

**Data integrity (negative).**
- **Corrupted/interrupted sync transfer** — simulate a sync that drops
  mid-upload or delivers corrupted records (kill WiFi mid-push, or
  inject a bad payload). Verify the reconciliation check catches the
  mismatch, does *not* mark those records `synced_at`, and retries
  cleanly at the next checkpoint rather than silently losing or
  duplicating data. Exact reconciliation mechanism (record-count vs.
  checksum) is an implementation-planning decision.
- **Malformed/low-confidence classification** — camera returns garbage
  or very low confidence. Verify it's logged as low-confidence rather
  than crashing the pipeline or being silently promoted to
  permanent-candidate.

**Telemetry verification.** Live-summary telemetry is observable in
real time during a run. The detailed log's sampling rate visibly drops
while idle vs. driving. After sync, the detailed log lands correctly in
the Mongo time-series collection with no data loss.

**UI sanity.** The local UI reads obstacle and telemetry data from
Mongo and supports the permanent-candidate confirm/reject workflow end
to end.

## Open items for implementation planning

These are real decisions but don't block the design — they're sized for
the planning/implementation phase:

- Pi ↔ ESP32 link: UART vs. USB
- Exact mast reuse decision: confirm 4tronix mast height/load specs
  against MP-1's sensor payload before committing
- Sync reconciliation mechanism: record-count vs. checksum
- Bump-sensor and GPS-dropout debug/test hooks: how they're exposed and
  who can trigger them (test harness only, or also a field debug
  command)
- PCB respin scope: full accounting of new connectors once Pi
  integration, mast sensors, and GPS are finalized

## Not in scope for MP-1

- LiDAR ([SEN-2](../../phase2/inputs/03-sensors-compute-electronics.md)) — deferred past v1
- Wheel encoders / IMU — deferred; GPS-only for now
- Map sector segmentation ([CAP-3](../../phase2/inputs/02-capabilities.md)) — single geofenced area only
- Cloud-hosted UI — local container hosting only
