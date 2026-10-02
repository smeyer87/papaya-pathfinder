# Changelog

All notable changes to this project are documented here. Versioning follows
[Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`):

- **MAJOR** — breaking/foundational changes (e.g. a new build phase, a
  hardware revision that invalidates prior wiring). Always consulted on
  before bumping.
- **MINOR** — new features or documentation additions that don't break
  what's already built (e.g. new firmware capability, new subsystem).
- **PATCH** — fixes, tuning, and small additions (e.g. trim values, BOM
  entries, doc updates).

## [2.2.3] - 2026-10-02

### Added
- `docs/adr/0004-wheeled-vs-tracked-drivetrain.md` — architecture decision
  record for keeping the wheeled rocker-bogie drivetrain over tracked/
  caterpillar, mecanum/omni, fully-independent-suspension, and legged
  alternatives, all considered and rejected in favor of retrofitting
  suspension at the one joint that's actually failing.
- `docs/phase2/inputs/04-physical-platform.md` / `05-assumptions-
  decisions.md`: first-pass mechanical/physical architecture
  brainstorm for the Phase 2 rebuild — payload bay enclosure-vs-
  footprint conflict and scale (PLT-5), a corrected diagnosis of the
  recurring wheel-strut failure as a 3D-printed steering-pivot pin
  carrying structural/impact load it was never sized for rather than
  an electrical connector (PLT-7), relocating the top-mounted
  transverse pivot link underneath the chassis (PLT-8), center-of-
  gravity weight budgeting for the larger bay (PLT-9, D-7), 6-vs-8-wheel
  drivetrain and steered-wheel-position decisions (Q-9, D-8), the
  second rear transverse link and chassis-torsion questions a dual-
  differential layout raises (Q-10, Q-11), the farm-terrain/walking-
  pace operating envelope (A-2), and drive-motor weatherproofing
  options. All open items are logged as open (TBD/leaning), not
  decided — follow-on discussion continues in a future session.

## [2.2.2] - 2026-10-02

### Added
- `MissionRuntime` gained an `ota_update` command handler: refuses to
  trigger an ESP32 firmware flash while a sweep session is actively in
  progress (checking session *status*, not mere presence — a session is
  never reset to `None` after a mission ends, so a presence-only check
  would have blocked OTA forever after the rover's first mission).

### Fixed
- A refused OTA command was believed to retry automatically via backend
  redelivery; the final review found this is false — the backend never
  moves a `"delivered"` command back to `"pending"`, so it was actually
  dropped permanently. The refusal itself was always correct and safe;
  only the retry claim was wrong. Corrected the code comments and docs,
  and added an explicit log line so a deliberate refusal is now
  distinguishable from a genuine fault. The backend-wide redelivery gap
  (affecting every command type, not just OTA) is logged as a follow-up,
  not fixed in this release.

## [2.2.1] - 2026-10-02

### Fixed
- `PositionFusion`'s fused heading only updated on ticks where no GPS fix
  arrived — on a GPS-healthy rover (the normal case), heading never
  advanced past its seed value, silently misplacing every obstacle the
  mission logs (bearing is projected from this heading). Found during the
  digital-twin simulator's final review (2026-09-26), fixed now: heading
  updates unconditionally every tick via a new, guard-free
  `PositionFusion.on_imu_heading()`, independent of GPS-fix dead-reckoning.
  The related seed-time gap (the first position estimate defaulted to
  heading `0.0` instead of the real IMU reading) is fixed too.

## [2.2.0] - 2026-10-02

### Added
- **Pi Mission Runtime (MP-1)**: the full `pathfinder-autonomous/pi-mission`
  Python client. A local SQLite store; `SensorHub`/`Esp32Link` interfaces
  with simulated/fake implementations for hardware-free testing; a backend
  read/poll client; and `MissionRuntime` itself — startup and resume-after-
  restart handling, `start_sweep`, a tick loop covering position fusion,
  obstacle detection, exclusion-zone and GPS-loss safety checks, command
  dispatch, telemetry cadence, Home-return sync, and a CLI entrypoint.
- **Digital-twin simulator** (`digital_twin.py`): a coherent simulated
  rover world (position/heading/speed, an autonomous bounded mast sweep,
  bounded GPS jitter, bump/halt detection) that derives consistent sensor
  readings from one shared state, so development and testing can continue
  end-to-end without physical hardware.
- **Breadboard bench rig hardware drivers**: `hardware_esp32_link.py` (a
  real `Esp32Link` over an injected UART transport), `hardware_sensor_hub.py`
  (GPS NMEA parsing, IMU, ultrasonic, and camera sources), and
  `status_display.py` (an LCD status display with screen cycling and
  soft-key dispatch) — every hardware dependency is injected against a
  `Protocol`, so none of this requires real hardware libraries to test.
- `MissionRuntime.last_telemetry_readings`, a live per-session obstacle
  counter, and ESP32 halted-on-contact status, wired into the LCD status
  display so it renders real runtime state end-to-end (deliberately kept
  out of the synced telemetry record for now — syncing it to ground
  control is a good longer-term idea, not built yet).

### Fixed
- The LCD drive screen couldn't distinguish "confirmed not halted" /
  "confirmed zero throttle" from "the status or drive-status read just
  failed" — both rendered identically.
- Resuming an interrupted sweep session after a process restart didn't
  seed the obstacle counter from obstacles already persisted for that
  session, and a confirmed re-detection during resume validation was
  double-counted against it.
- The LCD position screen's coordinate format silently overflowed the
  16-character display width and truncated longitude.
- A confirmed source of full-suite `pi-mission` test flakiness: two of
  `MissionRuntime`'s interval-gated timers (command-poll, telemetry-sample)
  could legitimately fire mid-test under system load, hitting test
  fixtures that hadn't been written to expect them.

## [2.1.0] - 2026-09-26

### Added
- MP-1 Backend Obstacle & Telemetry Sync: `POST /sync/sweep-sessions`,
  `/sync/obstacles`, `/sync/telemetry` — client-generated-ID upsert/insert
  sync for the Pi's sweep sessions, obstacles, and telemetry, plus a
  read-only `list_pending_review` for the Management UI plan to build on.
  Telemetry lands in a native MongoDB time-series collection.
- `docs/adr/0003-telemetry-sync-idempotency.md` — records the discovery
  that MongoDB rejects unique indexes on time-series collections, and the
  resulting move from database-enforced to application-level telemetry
  sync idempotency.

### Changed
- All three `/sync/*` endpoints now return `{"received": N, "inserted": M}`
  instead of `{"synced": N}` — the prior single field meant "processed"
  for sweep-sessions/obstacles but "newly inserted" for telemetry, an
  ambiguity a sync client couldn't reliably act on. No existing consumer
  depended on the old shape yet.
- Obstacle sync now preserves human review decisions (`review_status`,
  `reviewed_by`, `reviewed_at`, and a `permanent-confirmed` status) across
  a Pi re-sync, instead of a full-document replace silently reverting them.
- `MongoClient` now connects with `tz_aware=True`, so datetimes read back
  from MongoDB (e.g. `Rover.created_at`, `Obstacle.first_detected_at`)
  carry UTC tzinfo instead of coming back naive.

## [2.0.3] - 2026-09-23

### Added
- `docs/phase2/inputs/00-inbox.md` — first draft of offline Phase 2
  planning notes (mission packages, capability list, and related raw
  notes), captured unsorted. Triage into the numbered input files is
  deferred to the Phase 2 planning session.

## [2.0.2] - 2026-09-23

### Added
- `docs/phase2/inputs/` — structured templates for collecting Phase 2
  planning notes ahead of the design session: an inbox for unsorted
  notes, plus one file each for mission packages, capabilities,
  sensors/compute/electronics, physical platform updates, and
  constraints/assumptions/decisions/open questions. Items carry
  traceability IDs (`MP-`, `CAP-`, `SEN-`, `PLT-`, `Q-`, …) so each
  downstream item links back to the mission it supports. Phase 1
  baseline hardware constraints (GPIO usage, trimmed pins, power rails,
  open-loop drive) pre-filled from the repo.

## [2.0.1] - 2026-09-20

### Fixed
- Permanent fix for the servo header ground isolation defect (ADR 0002)
  applied to `pathfinder/kicad/papaya-pcb/papaya-pcb.kicad_pcb`: cut four
  zone cutouts into the `6V_POUR` zone on `B.Cu`, one behind each servo
  header GND pad, so the lower-priority `MASTER_GND` zone fills through
  to them on refill. Re-verified with `kicad-cli` DRC (0 violations,
  unconnected items down from 5 to 1 — the one remaining is the
  pre-existing, unrelated island near mounting hole `H1`) and with the
  same point-probe technique used to originally find the defect: real
  ground copper now reaches within 0.9mm of all four pads (previously
  nothing within 3–4mm), and the `6V_POUR` connection to each header's
  `PWR` pin was confirmed undisturbed.
- Gerbers and drill files in
  `pathfinder/kicad/papaya-pcb/gerbers/` regenerated to match. Board is
  ready to send to fab with this fix included — no more hand-wired ground
  jumpers needed on boards built from this revision.

### Added
- Minor `F.Silkscreen` identification text for a couple of components.

## [2.0.0] - 2026-09-19

Phase 1 baseline, pinned. Rover drives correctly end-to-end and this marks
the closing point of Phase 1 before Phase 2 (LIDAR/autonomy) design work
begins.

### Fixed
- Steering direction was reversed from stick input — this build's servo
  horns are mounted opposite the orientation the original channel-mapping
  math assumed. Fixed by inverting the steering channel reading in
  `firmware-elrs.ino`.

### Changed
- Throttle response: stick input is now squared (sign preserved) before
  driving the motors, giving finer control at low throttle instead of a
  1:1 linear mapping, plus an overall `THROTTLE_MAX` cap (0.6) as a
  top-speed limiter. Added after full-throttle testing was too aggressive
  off the line for indoor driving.

## [1.1.0] - 2026-09-19

Phase 1 complete: the rover drives under full ELRS control (steering,
throttle, spin-in-place all confirmed). Two real hardware defects were
found and fixed during final bring-up — full narrative in
[`docs/development-log.md`](docs/development-log.md#phase-1-bring-up-2026-08-20--2026-09-19).

### Added
- `docs/adr/0002-servo-header-ground-isolation.md` — architecture decision
  record for a PCB layout defect where all four servo header GND pads were
  physically isolated from the ground pour (boxed in by the 6V pour's
  territory), found via resistance testing and confirmed against the
  KiCad file itself. Documents the short-term hand-wired jumper fix in
  place now and the permanent routed-trace fix needed before any board
  reorder.
- `docs/build-guide.md` — start-from-scratch build guide covering BOM
  purchase through fabrication, assembly, firmware flashing, and bring-up
  testing, written to route around every pitfall hit during this build.

### Fixed
- Motor power distribution terminal block was wired incorrectly, shorting
  the motor supply; both motor channels now respond correctly to
  controller input.
- Servo header ground isolation (see ADR 0002 above) — hand-wired ground
  jumpers from `J8`'s ground terminal to each servo `GND` pin restore the
  connection the pour was supposed to provide.

### Changed
- `docs/superpowers/specs/2026-08-16-phase1-current-state.md` — all Phase 1
  exit criteria checked off except on-vehicle servo trim tuning (pending
  wheel attachment).

## [1.0.1] - 2026-09-09

### Added
- `docs/adr/0001-esp32-header-pin-trimming.md` — architecture decision
  record for trimming the ESP32 module's GPIO15/GPIO40 header pins (a pour
  boundary passes close enough between those two positions to risk an
  accidental short) instead of a full board respin or stripping every
  unused pin, and why the more aggressive option was rejected (mechanical
  retention risk on a full-size, vibration-exposed rover).
- `docs/servo-zeroing.md` — step-by-step procedure for flashing firmware
  and validating steering servo centering before horns are coupled to the
  steering linkage.

### Changed
- `docs/elrs-wiring.md` — reworked the ELRS binding instructions: the
  previously-documented "Method 1" binding-phrase flow doesn't work on
  this build's LiteRadio 2 SE (missing the BETAFPV Configurator
  compatibility sticker), so button-bind (chip-ID based) is now documented
  as the recommended method, with the binding-phrase flow kept only as
  reference and a callout on the root-cause gotcha (a receiver ever
  flashed with a binding phrase won't re-enter manual bind mode until that
  phrase is explicitly cleared).

## [1.0.0] - 2026-08-16

Baseline checkpoint. Version tracking starts here — prior work (wiring
model, KiCad PCB design, fabrication) predates this scheme and is described
in [`docs/development-log.md`](docs/development-log.md) rather than the
changelog.

### Added
- Semantic version tracking (`VERSION`, this changelog, git tags).
- `docs/superpowers/specs/2026-08-16-phase1-current-state.md` — Phase 1
  status snapshot and context anchor for the future Phase 2 (LIDAR/autonomy)
  brainstorming session.
- BOM entry for `U1` (UBEC 6V/8A), including Amazon ASIN.

### Changed
- Steering trims (`TRIM_LF/RF/LB/RB`) zeroed in
  `pathfinder/firmware-elrs/firmware-elrs.ino` to re-zero against the new
  Miuzei DS3218 servo horns; prior values were tuned for the previous
  servos and need on-vehicle re-tuning once horns are mounted.

### Status at this checkpoint
- PCB design complete, fabricated, boards received; premade Dupont headers
  acquired to replace hand-crimped connectors.
- Firmware bring-up in progress; servo re-trimming still required before
  servos/wheel assemblies can be connected for a full build.
