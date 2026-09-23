# 05 — Constraints, Assumptions, Decisions & Open Questions

Four different kinds of statement. Keep them separate. Treating an
assumption as a decision is the most common way a design goes wrong.

| Kind | Meaning | Changes when… |
|---|---|---|
| **Constraint** (`CON-`) | Hard limit or fact: budget, time, existing hardware | Rarely. Only when the situation changes |
| **Assumption** (`A-`) | Believed true, not yet verified | It's tested (becomes a fact, or gets disproven) |
| **Decision** (`D-`) | A choice already made, with its reason | It's deliberately revisited (log it as an ADR) |
| **Open question** (`Q-`) | Undecided; needs research or discussion | It's answered (becomes a decision) |

## Constraints

### Project constraints

- **CON-1 Budget:**
- **CON-2 Timeline / target date:**
- **CON-3 Skills / tools available** (3D printer, soldering, KiCad, languages):
- **CON-4 Time available per week:**

### Phase 1 baseline facts (from the repo, verified 2026-09-23)

- **CON-B1** Controller is an ESP32-S3-WROOM-1-N16R8 (16 MB flash, 8 MB
  octal PSRAM), socketed on Dupont headers.
- **CON-B2** GPIO in use by firmware: 7, 38, 41, 42 (servos);
  10, 11, 12, 13 (motor PWM); 47/21 (CRSF RX/TX); 48 (onboard RGB).
- **CON-B3** GPIO15 and GPIO40 are physically trimmed and unusable on the
  current board without rework
  ([ADR 0001](../../adr/0001-esp32-header-pin-trimming.md)).
- **CON-B4** Custom 2-layer PCB (OSH Park). Current Gerbers include the
  ADR 0002 servo-ground fix. Any new sensor connectors mean hand-wiring
  or a respin.
- **CON-B5** Power: 3S LiPo → 5V/3A UBEC (logic, on-board `U2`) and
  6V/8A UBEC (servos, off-board `U1`). The 5V/3A logic rail is the likely
  ceiling for new electronics.
- **CON-B6** Manual control is ELRS (CRSF at 420 kbaud). Drive is
  open-loop: no wheel encoders, no IMU.
- **CON-B7** `papaya-wiring-layout.yaml` is the electrical source of
  truth. New hardware gets modeled there first.

## Assumptions

### A-1:

- **Why we believe it:**
- **How to verify:**

## Decisions already made

### D-1:

- **Decision:**
- **Reason:**

## Open questions

These become the agenda for the design session.

### Q-1:

- **Options considered:**
- **Leaning:**
- **Blocks:** <!-- which MP/CAP/SEN/PLT items depend on this -->

## Raw notes

