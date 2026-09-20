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
