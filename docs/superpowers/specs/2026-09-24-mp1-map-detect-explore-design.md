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
- GPS + basic IMU dead reckoning (no wheel encoders) for positioning,
  with an explicit error-circle uncertainty model
- GeoJSON as the standard shape for all position/polygon data
- Store-and-forward data sync, checkpointed on every Home return
- Two-tier telemetry (live summary + bulk detailed log)
- Local, container-hosted Management UI reading from MongoDB
- Command delivery via a polled queue, live whenever WiFi is present
- Operator-triggered, idle-only software/firmware updates over WiFi
- Rover identity as a first-class registry entry, one active rover at a
  time (multi-rover concurrency is a roadmap item, not v1)

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

**Why not consolidate onto one board.** Revisited given the PCB respin
is happening anyway: a single Pi-only board was already ruled out in
the original compute decision, and that reasoning doesn't change with
the respin — Linux on the Pi isn't a real-time OS, and driving
PWM/servo/CRSF timing from Pi userspace risks the jitter a dedicated
microcontroller avoids. Replacing the ESP32-S3 with a Raspberry Pi Pico
(same vendor, still a two-controller split) is technically viable, but
it means rewriting the existing, working real-time drive/servo/CRSF
firmware from scratch on a different chip family for a
tooling-consistency benefit, not a capability one — not a favorable
trade against the risk of reintroducing bugs in code that already
works. Keeping the ESP32-S3 stands.

**Positioning.** GPS ([SEN-6](../../phase2/inputs/03-sensors-compute-electronics.md))
plus a basic IMU, fused for dead reckoning between fixes.

- **GPS accuracy, corrected.** A standard (non-RTK) hobby-grade GPS
  module realistically delivers ~1–3 m accuracy, not the decimeter
  figure this spec originally assumed — decimeter/centimeter accuracy
  is an RTK-only capability (fixed base station or paid correction
  service), not justified for MP-1's cost/complexity budget. Positions
  are still reported to 6 decimal places (precision) for consistency,
  but that precision does not imply that level of real-world accuracy.
- **IMU (reopens the earlier "no IMU" call).** A basic IMU
  (accelerometer + gyro, optionally magnetometer for heading) is added.
  Its accelerometer gives a short-term velocity estimate via
  integration, used with heading and elapsed time to dead-reckon
  position between GPS fixes — this reflects the rover's actual motion
  (wheel slip, terrain, speed variation) rather than assuming its
  commanded speed was achieved exactly. Still no wheel encoders. Pure
  inertial integration is known to drift within seconds without
  correction, which is acceptable here only because it's reset against
  each new GPS fix and only needs to bridge the gap *between* fixes, not
  navigate independently for any length of time.
- **Error circle.** Position carries a growing uncertainty radius
  between GPS fixes (widest just before the next fix, reset to the
  GPS's own accuracy figure at each fix). Exclusion-zone-proximity and
  auto-reverse decisions (Mission Flow) use the *outer edge* of this
  circle, not the bare point estimate — with ~1–3 m raw GPS uncertainty
  potentially comparable to the rover's own length, using the point
  estimate alone could make an intrusion look smaller than it actually
  is.

**Sensing.** GPS ([SEN-6](../../phase2/inputs/03-sensors-compute-electronics.md)),
the IMU, mast-mounted ultrasonic ([SEN-1](../../phase2/inputs/03-sensors-compute-electronics.md),
bearing + range), and the Pi AI Camera ([SEN-3](../../phase2/inputs/03-sensors-compute-electronics.md),
type classification) all attach to the Pi — MP-1's low travel speed
makes Pi-round-trip latency acceptable for obstacle detection and
mapping. Bump sensors ([SEN-4](../../phase2/inputs/03-sensors-compute-electronics.md))
attach directly to the ESP32 instead, so contact triggers an immediate
stop with no round-trip through the Pi. Multiple bump sensors share a
single I2C bus (SDA/SCL + one interrupt pin) via an I2C GPIO-expander
chip, rather than consuming one dedicated GPIO per sensor — I2C is a
standard two-wire shared bus available on both the ESP32 and the Pi,
not Pi-exclusive, and the expander's hardware interrupt line keeps the
ESP32's response effectively immediate regardless of how many sensors
are on the bus. The ESP32 relays the bump event up to the Pi for
logging. No LiDAR in this mission package.

No separate AI HAT — the Pi AI Camera already does its own edge
classification, so an inference accelerator solves a problem MP-1
doesn't have. No NVMe HAT — the obstacle list and telemetry log are far
too small to need it. Both are worth revisiting if a later mission's
needs (e.g. MP-2 image retention) outgrow onboard storage/compute.

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
ultrasonic mast wiring, a GPS module, and the IMU very likely force the
PCB respin already flagged in [CON-B4](../../phase2/inputs/05-assumptions-decisions.md),
plus the larger payload bay ([PLT-5](../../phase2/inputs/04-physical-platform.md))
needed to physically fit the Pi. The respin is scoped to guarantee
sufficient GPIO headroom on the ESP32 for known and near-term sensor
needs; the I2C bumper bus above is the primary lever if a dedicated-pin
sensor is ever added later, with the respin itself as the fallback if
I2C expansion isn't enough.

## Rover Identity & Fleet

MP-1 is being built against a single physical rover, but the platform
is expected to support multiple physical prototypes as Phase 2
progresses — e.g. an MP-1-only sensor build now, followed by a separate
MP-1+MP-2 build later, rather than always evolving one physical unit.

**Rover record.** Each physical rover is a document keyed by a Mongo
ObjectId, with a separately editable human-friendly `name` (e.g.
"George", "Rover1") — the ObjectId is the stable internal reference
(telemetry, sweep sessions, commands); the name is what operators see
and pick in the UI. Each record also carries the sensor manifest and a
supported-mission-package list (see Data Model below) — "which sensors
does this build have" and "which missions can it run" are properties of
the rover, not guessed per session.

**One active rover at a time (v1 assumption).** Multiple rover records
can exist in the registry simultaneously (different prototypes at
different build stages), but only one may have an active mission
running at any moment. Starting a mission on a rover while another
already has one active is rejected — an operator picks which rover
they're operating before issuing mission commands. The command queue
and telemetry are scoped per `rover_id` accordingly.

**Roadmap (out of scope for v1).** Multiple rovers operating
concurrently — implying each rover shares basic position/status with
the others for conflict avoidance, and lifting the one-active
constraint — is a real future direction, not a hypothetical. Flagging
it here so the `rover_id` scoping above doesn't need to be redesigned
later; the concurrent-operation logic itself is its own spec when that
need actually arrives.

## Command Channel

The Architecture section above covers rover → Mongo data flow; this
covers the reverse direction — UI → rover commands, including
mid-mission interrupts (a gap in the original pass).

**Mechanism.** The UI writes commands to a lightweight queue on the
local backend. The rover polls that queue frequently (on the order of
seconds) whenever WiFi is connected — command payloads are tiny, so
this doesn't conflict with the battery-conservation reasoning behind
checkpoint-only telemetry/obstacle sync. Each command targets a
specific `rover_id`, and a rover polls only its own queue. A command
issued while the rover is briefly unreachable simply waits in the queue
until the next successful poll, rather than being lost.

**Command set for MP-1.** Start sweep, pause sweep, resume sweep, stop/
abort sweep, abort-and-return-home, update geofence (applied to the
next run — not a mid-sweep boundary change). A broader command
vocabulary (e.g. switching mission packages) is a [CAP-7](../../phase2/inputs/02-capabilities.md)
concern for later missions, not MP-1.

**Interruption, revisited.** The "manual stop" branch in Mission Flow's
Interruption paragraph is this mechanism — an operator-issued pause/stop
command, handled identically to a Bingo Fuel trigger from the rover's
perspective (save progress locally, treat as resumable).

## Software & Firmware Updates

Not proposed for use during an active mission — this is about avoiding
physical USB connections for routine updates, not live/hot updates.

**Pi software.** New versions are staged (downloaded) whenever WiFi is
available. Applying a staged update — restarting the Pi's mission
service on the new version — requires an explicit operator-issued
"apply update" command from the UI, and only while the rover is idle
(not on a mission). Exact deployment mechanism (container image pull
vs. git-based deploy) is an implementation-planning decision.

**ESP32 firmware.** The Pi acts as the flash relay: it downloads new
ESP32 firmware over WiFi, then flashes it to the ESP32 over the existing
Pi↔ESP32 serial link using the same protocol a USB-connected laptop uses
today (esptool-class serial flashing) — no physical cable required.
Same operator-triggered, idle-only gating as Pi software updates, since
this touches the real-time drive controller.

## Mission Flow

**Pre-mission setup.** Given the geofence polygon (drawn in the UI,
[CAP-2](../../phase2/inputs/02-capabilities.md)), auto-generate a
lawnmower-style coverage pattern of waypoints, routed to avoid any
exclusion zones inside the fence. A resumed mission starts from its
saved coverage checkpoint instead of regenerating from scratch.

**Execution loop.** The rover drives waypoint-to-waypoint on the fused
GPS+IMU position estimate (Architecture: Positioning). While moving,
ultrasonic and the AI camera continuously scan for obstacles:

- **Detection.** Tag the obstacle with position (fused GPS/IMU fix +
  bearing/range, plus the error circle's current radius as
  `position_uncertainty_m`), a camera-classified type, and a
  permanent/temporary flag from
  a type heuristic (barrel/post/fence-type → permanent-candidate;
  chair/vehicle-type → temporary). Temporary tags go straight into the
  local obstacle list. Permanent-candidates are stored the same way but
  marked "pending review" — not treated as confirmed until a human
  confirms via the UI, post-sync ([CAP-3](../../phase2/inputs/02-capabilities.md)).
- **Bump contact.** Immediate stop, back off ([CAP-9](../../phase2/inputs/02-capabilities.md)),
  log an obstacle at the contact point with a low-confidence
  "contact-only" type, flagged for review.
- **GPS loss/degradation.** Continue on IMU-based dead reckoning
  (heading + accelerometer-derived velocity) for a short grace period,
  with the error circle growing throughout; stop and send a
  high-priority alert if GPS doesn't reacquire before the grace period
  elapses or the error circle exceeds a safe threshold.
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

All position and polygon data in the platform uses GeoJSON
(`Point`/`Polygon`/etc.) — MongoDB's native geospatial format, enabling
2dsphere indexes and geo queries (`$geoWithin`, `$near`,
`$geoIntersects`) directly, which matters most for
[CAP-2](../../phase2/inputs/02-capabilities.md)'s exclusion-zone
containment checks. **Coordinate order is `[longitude, latitude]`** —
the opposite of the lat/long ordering used casually elsewhere — worth
calling out since it's a classic source of silent bugs. Locally on the
rover (SQLite), the same GeoJSON structures are stored as serialized
JSON text; no local geospatial indexing is needed given the
single-sector scope.

**Rover.** `id` (Mongo ObjectId), `name` (human-editable display name),
`sensor_manifest` (installed hardware — feeds the telemetry
missing-vs-not-applicable logic below), `supported_mission_packages`
(list of MP IDs this build can run), `status` (active / inactive, per
the one-active-rover rule above), `created_at`/`updated_at`, `notes`.

**Geofence.** `id`, `type` (inclusive/exclusive), `boundary` (a GeoJSON
`Polygon`), `name`, `created_at`/`updated_at`. One inclusive fence plus
zero or more exclusive fences define MP-1's operating area. Source of
truth is MongoDB, with a 2dsphere index on `boundary` supporting the
containment queries behind exclusion-zone checks; the rover keeps a
local cached copy for offline operation. Sector segmentation
([CAP-3](../../phase2/inputs/02-capabilities.md)) is deferred — v1
treats the whole geofenced area as a single unit.

**Sweep session** (enables resume). `id`, `rover_id`, `geofence_id`, `status`
(in_progress / interrupted / completed), `pattern` (the generated
waypoint list — an ordered array of `{order, position}`, where each
`position` is a GeoJSON `Point`), `last_completed_waypoint_index`,
`started_at`, `interrupted_at`, `completed_at`. Interruption persists
this record locally with `status=interrupted` and the progress marker;
resume looks it up and continues from `last_completed_waypoint_index + 1`.

**Obstacle record.** `id`, `sweep_session_id`, `position` (a GeoJSON
`Point`, plus raw bearing/range as separate fields),
`position_uncertainty_m` (radius from the error-circle model at
detection time), `type` (camera classification label),
`classification_confidence`, `detection_method` (ultrasonic+camera /
contact-only), `status` (temporary / permanent-pending /
permanent-confirmed), `first_detected_at`, `last_confirmed_at` (updated
by resume-validation), `review_status` (pending / confirmed / rejected),
`reviewed_by`, `reviewed_at`, `synced_at` (null until pushed to Mongo).
A 2dsphere index on `position` supports proximity queries.

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
flexible `metrics` map. Repeated same-kind sensors use grouped arrays
rather than flat numbered keys, so a consumer can iterate without
knowing the count in advance:

```json
{
  "position": {"type": "Point", "coordinates": [-85.654321, 38.123456]},
  "position_uncertainty_m": 1.4, "gps_fix_quality": "3d",
  "battery_voltage": 11.8, "wifi_rssi": -52,
  "nav_mode": "sweep", "waypoint_index": 5,
  "motors": [{"id": 1, "current": 0.8}, {"id": 2, "current": 0.9}]
}
```

New metric keys (cell-level voltage once [PWR-1](../../phase2/inputs/03-sensors-compute-electronics.md)
lands, temperature once a sensor exists, etc.) just appear in the map —
no schema change or migration.

**Expected metrics & missing-value semantics.** A metric can be in one
of three states, and the distinction matters for troubleshooting:
present with a value; *expected but missing* (the hardware should have
produced it and didn't — something's wrong); or *not applicable* (this
rover/mission doesn't have that sensor at all). The Pi tags the second
case explicitly at write time — e.g. `"battery_voltage": "missing"` —
using a sentinel rather than a bare `null`, so it's visibly different
from a value. The third case is simply omitted from the map entirely;
nothing is written for metrics outside the current sensor
configuration. This only works if the Pi knows what to expect for the
current run, which is what the sensor manifest below provides.

**Sensor manifest.** "Expected metrics for this run" combines two
things: the sensor manifest stored on the active rover's record (see
Rover Identity & Fleet above — what hardware that specific physical
build actually has) and a per-mission-package expected-metrics list
(MP-1 expects GPS, pack-level battery, motor/servo status, WiFi signal,
nav status, mission status, error/event log). An operator can confirm
or edit a rover's manifest through the UI. Both the Pi (for
missing-value tagging) and the backend (for review/alerting on gaps)
use the same combined expectation.

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
- GPS loss/degradation → continues briefly on IMU-based dead reckoning
  (error circle growing), then stops and alerts if GPS doesn't
  reacquire before the grace period or uncertainty threshold is hit.
  **Negative test needs a debug hook** to force a "no fix"/degraded-fix
  state on demand — testing this only when GPS happens to actually drop
  isn't repeatable.
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
the Mongo time-series collection with no data loss. A deliberately
failed sensor read produces the `"missing"` sentinel on its metric; a
metric outside the current sensor manifest is correctly omitted rather
than written as missing — the two cases must be distinguishable in the
synced record.

**Command channel (happy path + negative).** Issuing pause/resume/stop/
abort-home commands mid-sweep through the queue is picked up and acted
on within the expected poll interval. **Negative:** a command issued
while the rover is briefly unreachable (WiFi dropped) is not lost — it's
applied on the next successful poll, not silently discarded. **Negative:**
a stale or conflicting command (e.g. "resume" arriving after an
abort-home is already underway) is handled gracefully — rejected or
ignored with a clear reason — not treated as valid and left to corrupt
the mission state.

**Software/firmware updates (happy path + negative).** An operator
stages and applies a Pi software update (or ESP32 firmware, relayed
through the Pi) while idle; the rover comes back functional on the new
version. **Negative:** an attempt to apply a staged update while a
mission is active is rejected with a clear error, not silently queued
and not silently applied mid-mission.

**UI sanity.** The local UI reads obstacle and telemetry data from
Mongo and supports the permanent-candidate confirm/reject workflow, and
the sensor-manifest confirm/edit workflow, end to end.

## Open items for implementation planning

These are real decisions but don't block the design — they're sized for
the planning/implementation phase:

- Pi ↔ ESP32 link: UART (direct 3-wire GPIO connection, no cable) vs.
  USB (ESP32's native USB, enumerates as USB-serial). UART's soldered/
  header connection is likely more vibration-resistant on a moving
  rover than a friction-fit USB cable — worth weighing alongside pin
  budget when this gets decided.
- Exact mast reuse decision: confirm 4tronix mast height/load specs
  against MP-1's sensor payload before committing
- ~~Sync reconciliation mechanism: record-count vs. checksum~~ — resolved:
  neither. Sweep sessions, obstacles, and telemetry all use
  client-generated IDs (UUIDs assigned by the Pi at creation time,
  before connectivity is guaranteed), making sync naturally idempotent —
  obstacles/sessions upsert by ID, telemetry inserts with duplicate-key
  errors on retry treated as already-synced. See the [Backend Obstacle &
  Telemetry Sync plan](../plans/2026-09-24-mp1-backend-obstacle-telemetry-sync.md).
- Local SQLite commit cadence on the Pi: batching writes on the order of
  "up to about a minute" is fine — gentle on the microSD card's write
  endurance, and it bounds worst-case rework on resume to about that
  same interval. Immediate per-sample commits aren't necessary. (User
  decision, 2026-09-24 — to be applied in the Pi Local Store & Sync
  Client plan.)
- Bump-sensor and GPS-dropout debug/test hooks: how they're exposed and
  who can trigger them (test harness only, or also a field debug
  command)
- PCB respin scope: full accounting of new connectors once Pi
  integration, mast sensors, and GPS are finalized
- I2C GPIO-expander part selection for the bump-sensor bus
- IMU part selection, and the exact error-circle growth-rate/threshold
  values used for the GPS-loss grace period and exclusion-zone margin
- Battery-backed RTC module selection (recommended addition, not yet in
  the BOM — see [`docs/reference/time-synchronization.md`](../../reference/time-synchronization.md))
- Command-queue implementation: exact poll interval, queue storage/
  transport on the local backend
- Pi software deployment mechanism: container image pull vs. git-based
  deploy
- Exact "missing" sentinel convention, applied consistently across all
  metrics
- UI rover-selector/activation flow: exact interaction for choosing and
  locking in the active rover before issuing commands
- Whether `supported_mission_packages` on a Rover record is manually
  curated or inferred from its sensor manifest

## Not in scope for MP-1

- LiDAR ([SEN-2](../../phase2/inputs/03-sensors-compute-electronics.md)) — deferred past v1
- Wheel encoders — deferred; IMU + GPS dead reckoning is now in scope (see Positioning)
- Map sector segmentation ([CAP-3](../../phase2/inputs/02-capabilities.md)) — single geofenced area only
- Cloud-hosted UI — local container hosting only
- RTK GPS — standard module only, revisit if accuracy proves insufficient
- Pi AI HAT — no need identified for MP-1's workload
- NVMe HAT — not required for MP-1's own storage needs (obstacle list +
  telemetry are small), but worth revisiting soon, not dismissing
  outright: retaining raw images/video for low-confidence-classification
  debugging, and MP-2's chicken individual-ID reference image library,
  both plausibly need real storage volume onboard storage doesn't
  comfortably provide. Hardware (HAT + drives) is already on hand.
  Revisit before or alongside MP-2. (User note, 2026-09-24.)
- Concurrent multi-rover operation and inter-rover position sharing for
  conflict avoidance — roadmap item, see Rover Identity & Fleet
