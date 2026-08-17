# Papaya Pathfinder — Phase 1 Current State

Status snapshot as of 2026-08-16, written as a context anchor for the Phase 2
(LIDAR / autonomy) brainstorming session — not a design doc itself. Links to
the existing detailed records instead of duplicating them.

## Project shape

Personal fork of the open-source [tronxi/papaya-pathfinder](https://github.com/tronxi/papaya-pathfinder)
rover, building the **full-size Pathfinder** (not `pathfinder-mini`) with a
from-scratch custom PCB and standard R/C control (ELRS) instead of upstream's
Android/desktop controllers.

Two-phase arc:
- **Phase 1** (this doc): get the rover physically assembled and reliably
  drivable on the custom PCB, running the stock/lightly-extended ELRS
  firmware. In progress now.
- **Phase 2** (not yet scoped): extend the firmware with LIDAR, additional
  sensors, and more autonomous behavior. Scope this with
  `superpowers:brainstorming` when it kicks off — nothing below should be
  read as a Phase 2 design.

## Hardware — fabricated, in assembly

- **Controller:** ESP32-S3. **Radio:** RadioMaster ELRS-RP3-V2 receiver +
  BETAFPV LiteRadio 2 SE transmitter (ELRS V3, 2.4 GHz). **Motor drivers:**
  2× BTS7960/IBT_2 driving 6× GA25 DC gear motors (3 ganged per side).
  **Steering:** 4× servos (front/rear axles) — recently upgraded to Miuzei
  DS3218 horns. **Power:** LiPo 3S → UBEC 5V/3A (logic, on-board, `U2`) +
  UBEC 6V/8A (servos, off-board, `U1`).
- **PCB:** 2-layer custom board, designed YAML-first
  ([`papaya-wiring-layout.yaml`](../../../papaya-wiring-layout.yaml) is the
  system source of truth), laid out and routed by hand in KiCad (the user's
  first KiCad project), 0 DRC violations, full net-by-net parity verified
  against the YAML, ordered from and received back from OSH Park. Full
  narrative in [`docs/development-log.md`](../../development-log.md).
- **Connectors:** switched to premade Dupont headers for some connections —
  hand-crimping custom Dupont connectors wasn't going well.
- **U1 (6V/8A UBEC):** ships in factory heat-shrink wrap with only
  input/output wires and the voltage-select jumper exposed; jumper set to
  6V. Decided to leave the wrap on — it's a switching (not linear) regulator
  so heat output is modest at expected loads, and the shrink tubing's rated
  continuous-use temperature is well above what it'll see. Resolved
  2026-08-16.
- Full parts list with Amazon ASINs and measured footprints:
  [`pathfinder/BOM.md`](../../../pathfinder/BOM.md).

## Firmware — stock ELRS base, in bring-up

- [`pathfinder/firmware-elrs/firmware-elrs.ino`](../../../pathfinder/firmware-elrs/firmware-elrs.ino)
  (~200 lines) is the upstream base firmware, extended for this fork's ELRS
  wiring — CRSF over HardwareSerial2, channel mapping for steering/throttle/spin.
  See [`docs/elrs-wiring.md`](../../elrs-wiring.md) for the full wiring,
  binding, and channel-mapping reference. No autonomy or sensor logic exists
  in it yet.
- **In-progress uncommitted change:** all four steering trims
  (`TRIM_LF/RF/LB/RB`) zeroed out to re-zero against the new DS3218 servo
  horns — the old trim values were tuned for the previous, different
  servos. Needs on-vehicle re-tuning once horns are mounted and steering
  centering is verified.
- `firmware-wifi/firmware-wifi.ino` exists in the upstream tree but is not
  part of this fork's control path (ELRS was chosen over WiFi control).

## Phase 1 exit criteria

- [ ] Rover fully assembled on the custom PCB
- [ ] ESP32 firmware pin assignments verified against the wiring YAML,
      pin-by-pin, before first power-on
- [ ] ELRS transmitter/receiver bound; steering, throttle, and spin-in-place
      all respond correctly
- [ ] All 4 steering servos re-trimmed straight on the new DS3218 horns
- [ ] Drivetrain (6× GA25 via 2× BTS7960) responds correctly across the full
      throttle range
- [x] UBEC heat/shrink-wrap question resolved (2026-08-16)

## Source-of-truth documents

Don't re-derive these — read them directly when more detail is needed.

| Doc | Covers |
|---|---|
| [`pathfinder/BOM.md`](../../../pathfinder/BOM.md) | Purchased parts, ASINs, measured footprints |
| [`papaya-wiring-layout.yaml`](../../../papaya-wiring-layout.yaml) | Full electrical system model (source of truth for the schematic) |
| [`docs/development-log.md`](../../development-log.md) | Wiring model + KiCad PCB design narrative, mistakes caught, verification discipline |
| [`docs/elrs-wiring.md`](../../elrs-wiring.md) | ELRS receiver wiring, binding, RC channel mapping |
| [`docs/build-notes.md`](../../build-notes.md) | Original build journal / gap analysis vs. upstream docs |

## Phase 2 — intentionally unscoped here

Known direction only: LIDAR, additional sensors, more autonomous features,
extending the current firmware package. Open questions (sensor selection,
ESP32 compute/pin budget, onboard vs. offboard autonomy compute, how it
coexists with the existing ELRS manual-control path) are deliberately not
answered in this doc — that's what the Phase 2 `superpowers:brainstorming`
session is for.
