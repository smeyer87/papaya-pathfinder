# Papaya Pathfinder — Autonomous (Phase 2) BOM

Running parts tally for the `pathfinder-autonomous/` rebuild. Started
2026-09-24 during MP-1 planning. Companion to the Phase 1 BOM at
[`pathfinder/BOM.md`](../pathfinder/BOM.md), which stays as the
historical record for the original build — this file is Phase 2's own,
not a replacement.

## Status legend

| Status | Meaning |
|---|---|
| **Verified** | Purchased, in hand, measured/confirmed working (Phase 1 build) |
| **Purchased — Unverified** | In hand, but not yet confirmed equivalent/working |
| **On Hand — Design Pending** | Owned already, but not yet decided whether/how it's used |
| **Pending Selection** | Required or recommended for Phase 2; no specific part chosen yet |

Descriptive/requirements-only entries come first for anything still
`Pending Selection`; each gets amended with real ASIN/URL/measured
footprint once a part is actually bought, same discipline as the Phase 1
BOM.

---

## Reused from Phase 1 — Verified

Copied from [`pathfinder/BOM.md`](../pathfinder/BOM.md) — these are
expected to carry over into the Phase 2 build unchanged.

- **PCB Screw Terminal Assortment** — general screw terminal attachments.
  Amazon URL: https://www.amazon.com/dp/B0D1GMMTZ5?ref=ppx_yo2ov_dt_b_fed_asin_title&th=1
  Amazon ASIN: B0D1GMMTZ5
  Usage: Primary off-board connectors for incoming power and ground, plus
  connections from ESP32 to BTS motor controller signal connections. The
  BTS connections could be header pin based if needed to conserve board
  space.
  Footprint: Single connectors at approximately 5mm square, but can be
  combined into multiple component blocks at 5mm increments.

- **UBEC 5V/3A** — tagged as `U2`.
  Amazon URL: https://www.amazon.com/dp/B07PLSYX9G?ref=ppx_yo2ov_dt_b_fed_asin_title
  Amazon ASIN: B07PLSYX9G
  Footprint: rectangular with 4 pins at the corners, approx 10mm x 15mm.
  Input and output pins are on the 'short' sides.

- **UBEC 6V/8A** — tagged as `U1`.
  Amazon URL: https://www.amazon.com/dp/B07DD9L6P6?ref=ppx_yo2ov_dt_b_fed_asin_title
  Amazon ASIN: B07DD9L6P6
  Footprint: Off board. Connect output from U1 into screw terminals.

- **ESP32-S3 Development Board** — used for ESP32 footprint. Remains the
  real-time drive/servo/ELRS controller in the Phase 2 hybrid
  architecture (design spec: Architecture — "Why not consolidate onto
  one board").
  Amazon URL: https://www.amazon.com/dp/B0F5QCK6X5?ref=ppx_yo2ov_dt_b_fed_asin_title&th=1
  Amazon ASIN: B0F5QCK6X5
  Footprint: NOT a single 2x22 block -- two separate 1x22 P2.54mm header
  rows (Espressif calls them J1/J3). Measured row-to-row centerline
  spacing was 25.5-26.0mm; deliberately loosened to 25.40mm row spacing /
  2.0mm pad / 1.1mm drill for assembly tolerance rather than targeting
  the raw measurement exactly. Pin 1 of both rows is at the same end of
  the board; row orientation corrected after an initial mirrored build
  (J1-origin pins on the +Y row, J3-origin on -Y). Custom footprint:
  `pathfinder/kicad/papaya-pcb/papaya-pcb.pretty/ESP32S3_DevKit_2x1x22_split.kicad_mod`,
  pin assignment per Espressif's published ESP32-S3-DevKitC-1 J1/J3
  tables.

- **Other connectors** — standard header pins.
  - Servo connectors S1, S2, S3, S4: 3-pin male headers (black/red/white
    sequence)
  - Radio receiver connector J4: 4-pin male headers (Red/Black and
    Green/White)

## Reused from Phase 1 — Purchased, Unverified

- **ESP32-S3 Development Board (alternate stock)** — the original
  vendor listing (ASIN `B0F5QCK6X5` above) went out of stock after the
  last purchase. Backup inventory on hand from a different listing,
  claimed by the seller to be the same underlying board.
  Amazon URL: *(fill in when confirming — not yet recorded)*
  Amazon ASIN: *(different from `B0F5QCK6X5` — fill in)*
  **Needs verification before use:** confirm pinout/footprint actually
  matches the measured `ESP32S3_DevKit_2x1x22_split` footprint above
  before relying on it for a build — "purports to be the same
  component" isn't confirmed yet.

---

## On Hand — Design Decision Pending

Owned already; not yet decided whether Phase 2 actually uses them.

- **Raspberry Pi NVMe HAT + NVMe drive(s)** — not required for MP-1's
  own storage needs (obstacle list + telemetry are small — see the
  [design spec](../docs/superpowers/specs/2026-09-24-mp1-map-detect-explore-design.md)'s
  "Not in scope for MP-1"), but a real consideration for image/video
  retention: raw captures for low-confidence-classification debugging,
  and MP-2's chicken individual-ID reference image library, both
  plausibly need real storage volume beyond what's otherwise available.
  Not mandated yet — revisit before or alongside MP-2.

---

## New for Phase 2 — Confirmed, On Hand

Architecture/part decision made (see `docs/phase2/inputs/`); already
owned, no purchase needed.

- **Raspberry Pi 5** (4GB or 8GB, both on hand) — mission-logic/
  perception controller (D-6, Architecture: Compute split). Paired with
  the existing ESP32-S3, not replacing it. NVMe HAT also on hand, not
  required for MP-1's own storage but a candidate for image/video
  retention later (see "On Hand — Design Decision Pending" above).
  Amazon URL/ASIN: *(fill in from order history)*

- **Raspberry Pi AI Camera** — obstacle type classification (SEN-3),
  edge inference on-device. v1 unit on hand (confirmed, D-6); a v2 may
  also be on hand, unverified. A Pi HD Camera (non-AI) is also available
  as a fallback/secondary.
  Amazon URL/ASIN: *(fill in from order history)*

## New for Phase 2 — Purchased, Unverified

Specific SKU chosen and bought; not yet confirmed working on a real
bench.

- **GPS: SparkFun NEO-M9N (SMA variant)** — confirmed long-term pick
  (SEN-6, 2026-09-30): verified active/production, u-blox's own
  recommended migration target away from the NRND NEO-M8N, open
  schematics, panel-mount SMA for a separately-mounted antenna.
  **Needs a GPS-specific external antenna** — the SMA board has no
  onboard patch, and this hasn't been sourced yet.
  Amazon URL/ASIN: *(fill in from order history)*
  - Also on hand as a spare/fallback: **MicroAir M10G** — has an
    embedded 18×18×4mm patch antenna (no external antenna needed), plus
    a bundled QMC5883L magnetometer noted as a possible future IMU
    component (see IMU entry below).
    Amazon URL/ASIN: *(fill in from order history)*

- **IMU: Adafruit BNO055** (active) **and SparkFun ICM-20948** (swap-in
  alternate) — bought for breadboard bench evaluation (SEN-5,
  2026-09-30). **Both NRND — not for the permanent PCB.** BNO055 is
  NRND; ICM-20948 faces an imminent Last-Time-Delivery (~2026-10-30),
  AKM discontinuing the AK09916C magnetometer it depends on. TDK's
  suggested replacement path for the real build: ICM-42688-P/42670-P
  (6-axis) + a separate magnetometer (the MicroAir GPS board's bundled
  QMC5883L is a candidate). Still open — revisit before the PCB respin.
  Amazon URL/ASIN: *(fill in from order history, both parts)*

- **LCD: 1602A 16×2 character display + PCF8574 I2C backpack**
  (address `0x27`) — confirmed (COM-5, 2026-09-30), matches
  `github.com/UCTRONICS/KB0005`'s reference driver. Two backpack-
  equipped units on hand (one active, one spare), plus a third bare
  1602A (no backpack) as spare. Powered from the Pi's 5V pin.
  Amazon URL/ASIN: *(fill in from order history)*

---

## New for Phase 2 — Pending Selection

Everything below is required or recommended by the
[MP-1 design spec](../docs/superpowers/specs/2026-09-24-mp1-map-detect-explore-design.md)
but has no part chosen yet. No ASINs/URLs are included here — none
have been picked, so none are recorded.

- **Ultrasonic sensor** — mast-mounted, bearing + range obstacle
  detection (SEN-1). Starting candidate: the HC-SR04-class unit already
  bundled on the 4Tronix M.A.R.S. Rover mast, alongside its camera mount.

- **Bump sensors** — minimal set at the rover corners, wired to the
  ESP32 directly for zero-latency stop response (SEN-4, Sensing).
  Breadboard bench rig uses 2 (left/right) as a first pass; production
  count/placement (all 4 axle corners, possibly also payload-bay
  corners) still open — see SEN-4 in
  `docs/phase2/inputs/03-sensors-compute-electronics.md`.

- **I2C GPIO-expander: PCF8574** — confirmed for the breadboard (lets
  the 2 bump switches share one I2C bus plus an interrupt pin on the
  ESP32, instead of one dedicated pin per switch — the "bumper bus,"
  Architecture: Sensing/PCB impact). The LCD's backpack is also a
  PCF8574 at a different address (`0x27`), so no new chip-level part
  is needed beyond what the LCD already brought.

- **Battery-backed RTC module** — recommended addition (I2C, coin-cell
  backed, e.g. DS3231-class) so the Pi has a reasonable time reference
  immediately on a cold field boot, before GPS gets a fix. See
  [`docs/reference/time-synchronization.md`](../docs/reference/time-synchronization.md).

- **Mast** — evaluate reusing the 4tronix M.A.R.S. Rover mast (already
  integrates ultrasonic + a camera-class sensor + a small rotation
  servo) before committing to a custom design; confirm height/load
  specs are sufficient for this build's sensor payload (Architecture:
  Mast).

- **Pi ↔ ESP32 link hardware** — **confirmed: UART** (direct 3-wire
  GPIO, no cable), for vibration-resistance on a moving rover. Already
  wired this way on the breadboard (`docs/wiring/breadboard-wiring-layout.yaml`)
  and implemented in `hardware_esp32_link.py` (newline-delimited JSON
  over the UART transport).
