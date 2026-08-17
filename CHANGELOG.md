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
