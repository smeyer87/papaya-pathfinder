# 03 — Sensors, Compute & Electronics

Hardware needed to deliver the capabilities in
[`02-capabilities.md`](02-capabilities.md). Specific part names are
welcome here, including "candidates I'm considering" — note links,
prices, and why.

Phase 1 electronics baseline: see
[`../../superpowers/specs/2026-08-16-phase1-current-state.md`](../../superpowers/specs/2026-08-16-phase1-current-state.md)
and [`../../../pathfinder/BOM.md`](../../../pathfinder/BOM.md).

## Sensors

<!-- Copy per sensor. -->

### SEN-1: Ultrasonic

- **Supports:** CAP-9, MP-1
- **Candidates:** HC-SR04-class trigger/echo module — starting point is
  the unit already bundled on the 4Tronix M.A.R.S. Rover mast (alongside
  its Pi AI Camera mount), since that mast is also a PLT-2 reuse
  candidate. Any HC-SR04-class module reaches ~3-4m reliably on
  reasonably-sized, perpendicular targets — soft/angled/small targets
  reduce effective range, a physics limit of the technology, not a
  specific part's shortcoming. I2C ToF modules (VL53L0X/L1X-class) were
  considered and rejected for this role: shorter max range (~2-4m) and
  known to struggle outdoors in direct sunlight (ambient IR swamps the
  sensor) — a real problem for a farm rover, not just a range tradeoff.
- **Interface/owner (see D-6):** Pi-managed via GPIO trigger/echo
  (`pigpio`'s DMA-based edge timing keeps microsecond accuracy despite
  Linux scheduling jitter — a well-trodden HC-SR04+Pi combo). Chosen
  over ESP32-managed specifically to avoid inventing a new
  ultrasonic-over-UART message on the Pi↔ESP32 link, and to keep all
  ranging sensors (camera + ultrasonic) consistently Pi-side.
- **Mounting needs:** Assumes a rotating mast (PLT-2); provides bearing
  and range.
- **Notes:** Considered an obvious "yes" — low power, low capability,
  easy to integrate for basic bearing-and-range sensing.
- **Vertical beam cone — plan to test empirically (2026-09-30):** an
  HC-SR04-class sensor's vertical beam is narrow (~15° effective), and
  whether it covers payload-bay height (vs. only ground-level
  obstacles) depends on mount height and distance, neither fixed yet.
  Rather than calculate this from a datasheet, once the breadboard's
  ultrasonic is wired up: move a target vertically at a few distances
  and record where detection drops out. Feeds directly into SEN-4's
  payload-bay-corner bump-sensor question — if the cone already covers
  that height, a bump sensor there is redundant; if not, it's the gap
  that sensor needs to close.

### SEN-2: LiDAR

- **Supports:** CAP-3, CAP-9
- **Candidates:** Not yet specified.
- **Mounting needs:** Mast-mounted, TBD.
- **Notes:** Higher power draw than ultrasonic. Primary value seen in
  the mapping mission (MP-1). Open question on whether it's useful at a
  reduced scan frequency for general (non-mapping) use to limit power
  draw (see Q-2 in
  [`05-assumptions-decisions.md`](05-assumptions-decisions.md)).

### SEN-3: AI Camera (Raspberry Pi AI Camera)

- **Supports:** CAP-8, MP-2, MP-4
- **Candidates:** Raspberry Pi AI Camera — edge object classification.
  **Confirmed (D-6, 2026-09-30):** v1 unit already owned; a v2 may also
  be on hand, unverified. A Pi HD Camera (non-AI) is also available as a
  fallback/secondary. Connects via the Pi's CSI port.
- **Mounting needs:** TBD — co-mounted with SEN-1 on the 4Tronix mast is
  the starting candidate.
- **Notes:** High priority — some form of camera is required in all
  scenarios. The Pi AI Camera's edge-classification capability was the
  key factor pulling the platform toward the hybrid controller design
  (see D-6 in 05).

### SEN-4: Touch / Bump Sensors

- **Supports:** CAP-9
- **Candidates:** Not yet specified — a minimal set at the rover
  corners. **Breadboard bench rig (2026-09-30):** 2 switches (left/right)
  for this first pass — see `docs/wiring/breadboard-wiring-layout.yaml`.
- **Production count/placement (2026-09-30):** leaning toward all 4
  axle corners, possibly *also* the payload bay's corners if it ends up
  tall enough — not just ground-level. Open question: whether the
  payload-bay height falls inside or outside SEN-1's ultrasonic vertical
  beam cone. If it's inside the cone, the ultrasonic may already catch
  mid-height obstacles the camera/ultrasonic combo would otherwise miss
  (a signpost, a branch at hip height); if it's outside, that's exactly
  the gap a payload-bay-corner bump sensor would need to cover. See
  SEN-1's note on empirically testing the real cone once the breadboard
  sensor is wired up, rather than guessing from a datasheet.
- **Mounting needs:** Corner-mounted, low to the ground (to catch
  obstacles below the height of ultrasonic/LiDAR/camera sensing) — and
  possibly also at payload-bay-corner height, pending the vertical-cone
  question above.
- **Notes:** Should give immediate stop-forward-motion feedback; ideally
  integrates with CAP-9 to interrupt the current path and back away/
  reroute around the detected object. Motivation (2026-09-30, from real
  test runs): small ground obstacles — a fallen branch, a rut, tall
  grass/plants — likely won't register via camera or ultrasonic at all,
  but still impair wheel operation; see the training-mode inbox note for
  the related idea of capturing recovery maneuvers for these cases.

### SEN-5: IMU (Inertial Measurement Unit)

- **Supports:** CAP-9, CAP-3
- **Interface class settled:** I2C (4-wire, shares a bus trivially with
  other I2C devices — near-zero pinout risk). 9-DOF with a magnetometer
  (not a bare 6-DOF accel/gyro-only part like the MPU-6050), since
  `papaya_mission.position_fusion.ImuReading.heading_deg` is a compass
  heading, which a 6-DOF part can't directly provide.
- **Purchased for bench evaluation, both NRND (2026-09-30):** Adafruit
  BNO055 (onboard sensor fusion — fastest path to a working
  `heading_deg`) and SparkFun ICM-20948 board. Both fine for breadboard
  eval, but **not for the permanent PCB** — BNO055 is NRND, and the
  ICM-20948 faces an imminent Last-Time-Delivery (~2026-10-30) because
  AKM is discontinuing the AK09916C magnetometer it depends on. TDK's
  own suggested replacement path: ICM-42688-P/42670-P (6-axis only) plus
  a separate current magnetometer — the QMC5883L already bundled on the
  spare MicroAir GPS board (see SEN-6) could plausibly fill that role
  later without a new purchase. Process lesson from this purchase:
  verify NRND/EOL status before buying a specific SKU, not just
  confirming the interface class.
- **Breadboard wiring (2026-09-30):** wired one at a time, not
  simultaneously — BNO055 active, ICM-20948 as a direct swap-in using
  the same 4 points (SDA/SCL/VCC/GND). See
  `docs/wiring/breadboard-wiring-layout.yaml`.
- **Interface/owner (see D-6):** Pi-managed, I2C.
- **Mounting needs:** TBD.
- **Still open for the permanent PCB:** exact SKU, given both on-hand
  parts are NRND. Revisit before the real board respin — TDK's
  suggested path above is the current leaning, not yet decided.

### SEN-6: GPS

- **Supports:** CAP-2, CAP-3, CAP-11, CAP-4
- **Interface class settled:** UART/NMEA-0183 (4-wire — near-zero
  pinout risk). u-blox NEO-family (NEO-6M/7M/8M/M9N/M10) is the de facto
  hobby/prosumer standard, consistent pinout across the family, heavily
  documented.
- **Confirmed long-term pick (2026-09-30): SparkFun NEO-M9N (SMA
  variant).** Verified active/production, u-blox's own recommended
  migration target away from the NRND NEO-M8N, open schematics, panel-
  mount SMA for a separately-mounted antenna. Chosen on the merits for
  long-term use, not optimized for breadboard (Qwiic) convenience. Also
  on hand for bench eval: MicroAir M10G (has an embedded 18×18×4mm patch
  antenna, no external antenna needed — a useful spare/fallback, bundled
  QMC5883L magnetometer noted under SEN-5 as a possible future IMU
  component).
- **Gap: GPS-specific antenna not yet sourced.** The NEO-M9N SMA board
  expects an external antenna (no onboard patch) — needs sourcing before
  the breadboard can get a real fix, independent of the Q-6 antenna-mast
  question (GPS/LoRa/ELRS each need their own distinct, correctly-tuned
  antenna; they cannot share one — see Q-6 in 05).
- **Interface/owner (see D-6):** Pi-managed, UART.
- **Decimeter-accuracy target may be stricter than actually needed** —
  worth checking against `position_fusion.py`'s existing dead-reckoning
  error budget (`GPS_LOSS_MAX_ERROR_RADIUS_M = 5.0` in the Mission
  Runtime code already tolerates several meters of drift between fixes)
  before shopping for RTK-class hardware to hit decimeter accuracy.
- **Mounting needs:** Antenna integration TBD (see Q-6 in 05).
- **Notes:** Almost certainly mandatory. Update frequency can be
  moderate — rover is low-speed, so a few fixes per minute is likely
  sufficient. HDOP-based accuracy heuristic (`accuracy_m = hdop * 5.0`)
  is implemented in `hardware_sensor_hub.py`, documented there as an
  approximation to refine once real bench fix data exists.

## Compute

Where does the thinking happen? The ESP32-S3 alone, the ESP32 plus a
companion computer (Raspberry Pi, Jetson, etc.), or offboard (laptop over
WiFi)? Capture leanings and reasons, even if undecided.

### CMP-1: Core platform architecture

- **Supports:** CAP-8, CAP-9, CAP-3, all missions
- **Decided (D-6):** Hybrid — Pi runs mission logic and owns all
  sensing (GPS/IMU/ultrasonic/camera); ESP32 stays scoped to drive-train
  actuation, bump-safety interrupt, drive-status, geofence push (purpose
  TBD — not yet called by `MissionRuntime`), and OTA (Pi downloads over
  WiFi, flashes the ESP32 locally over the serial link — no independent
  ESP32 networking either way). **Pi model: Raspberry Pi 5** (4GB or
  8GB, both on hand; NVMe HAT available to avoid SD-card wear) — see
  D-6 in [`05-assumptions-decisions.md`](05-assumptions-decisions.md).

## Power

New loads, runtime targets, battery changes, extra regulator rails.

### PWR-1: Cell-level LiPo monitoring

- **Notes:** Currently uses a separate manual balance-lead dongle to
  read cell voltages. Want to build a connector that captures per-cell
  voltage through this connection and feeds it into telemetry (CAP-4),
  enabling low-voltage alarms that protect the battery.

### PWR-2: Additional power measurement points

- **Notes:** Open question on which additional points are worth
  instrumenting for voltage/current — e.g. per-motor/per-servo, per-
  sensor, per-rail (see Q-5 in 05). Sampling should be configurable:
  full detail at startup as a validation check, then reduced-frequency
  sampling in normal operation to limit telemetry volume, with
  mission-driven toggles for detail level and sample rate. If a
  multi-battery configuration is adopted, power management must cover
  all sources.

### PWR-3: Charging & solar assist

- **Parts on hand (2026-09-30):** several small lightweight 7.2V/200mA
  solar panels, earmarked for logic/electronics only, not motors/servos
  — matches the "sustain control electronics/radios, not drive" lean
  below. Not a critical decision yet.
- **Main battery:** 5000mAh 3S LiPo, already in use and reported to do
  well at the rover's low-speed Phase 1 operation (see CON-B5 for the
  existing UBEC/power-rail baseline).
- **Notes:** Onboard solar considered "nice to have" — likely
  insufficient for motors/servos but might sustain control electronics/
  radios at a lower bulk/weight cost (see Q-7 in 05). Independent of
  solar, want easily accessible charging points, ideally without
  removing batteries; any external power connection needs a cover to
  avoid short-circuit risk from weather.

## Communications & telemetry

Video, telemetry back to the operator, WiFi/ELRS telemetry, data logging,
remote kill switch.

### COM-1: WiFi

- **Confirmed (D-6):** Pi 5 has onboard WiFi — this is the rover's
  comms path (backend sync, OTA firmware download, Management UI). Not
  the ESP32's job; see D-6.
- **Notes:** High bandwidth, limited range; suitable for local/on-
  premise hosting.

### COM-2: LoRa / LoRaWAN

- **Parts on hand (2026-09-30):** LoRa hardware available, not yet
  used. Would need a matching receiver device at the garage base
  station — inherent to point-to-point LoRa, not an added complication
  — likely a small Pi Pico- or ESP-class board, a separate build from
  the rover itself. Deferred; not a breadboard concern.
- **Confirmed low-risk to defer (2026-09-30):** no pin/bus conflict
  with anything decided so far — common LoRa modules are SPI (unclaimed
  by GPS/IMU/ultrasonic/camera) or a self-contained UART module, and Pi
  5's RP1 makes a second UART easy if needed. Software-wise it's
  additive — a new module parallel to `backend_client.py` carrying a
  small command/telemetry message set, not a retrofit of sensing or the
  existing HTTP sync path (which can't carry LoRa's bandwidth anyway).
  Note `local_store`'s store-and-forward design already tolerates WiFi
  gaps today (buffers and catches up the backend later) — LoRa's real
  marginal value is *real-time* command/telemetry while actually out of
  WiFi range (e.g. a remote stop), a genuinely new capability worth
  having for a true field build, not a fix for something broken.
- **Notes:** Long-range, low-power; for basic telemetry and low-
  bandwidth commands; not suitable for large data transfers (e.g.
  images/maps).

### COM-5: Local status LCD

- **Supports:** CAP-4 (telemetry), general bench/field validation.
- **Confirmed (2026-09-30): 1602A 16×2 character LCD with a PCF8574 I2C
  backpack, address `0x27`** — matches `github.com/UCTRONICS/KB0005`'s
  reference driver exactly. Two backpack-equipped units on hand (one
  active, one spare), plus a third bare 1602A (no backpack) as spare.
  Powered from the Pi's 5V pin. An "Inland 3.5 inch TFT Touch Screen
  Monitor" and standard 7" Pi displays are also on hand as alternates,
  not used for this role.
- **Interface/owner (see D-6):** Pi-managed, I2C. No address conflict
  with anything decided so far (IMU 0x28/0x68-class, GPS I2C mode 0x42,
  QMC5883L 0x0D).
- **Subscreen content and navigation, built (2026-10-01):** implemented
  in `papaya_mission/status_display.py` — 4 screens (position/heading,
  mission mode+alert, obstacle count+last type, drive throttle+halted
  status), cycled via up/down buttons, with 2 soft-key function buttons
  whose meaning depends on the current screen. Reads
  `MissionRuntime.last_telemetry_readings`, the same state the
  telemetry pipeline samples — a live cross-check on what the same
  tick's record reports, as originally proposed. Real hardware write
  backend (the actual PCF8574 byte-banged protocol) is bench-time work,
  not yet built.

### COM-3: Cellular

- **Notes:** Out of scope for Version 2 (see D-1 in 05) — cost and SIM/
  plan overhead not justified. A far-future self-hosted legacy 1G/2G
  private network was floated but is explicitly not a Version 2
  concern.

### COM-4: Zigbee mesh (rover-to-rover relay)

- **Notes:** "Nice to have" multimode capability — would let rovers
  relay messages to each other to extend effective range.

## PCB / wiring impact

Anything you already know about new connectors, a board respin, and so
on. (See constraints in `05` for current pin availability.)

- Any new sensor connectors (cell-tap for PWR-1, bump sensors, IMU,
  LiDAR, AI camera, GPS) mean hand-wiring or a board respin against the
  current 2-layer PCB (CON-B4).
- Antenna consolidation (single mast-integrated antenna structure vs. a
  "nest" of separate antennas for ELRS/LoRa/WiFi/GPS) affects both
  feed-line routing and mast design — open question, see Q-6 in 05 and
  PLT-2 in [`04-physical-platform.md`](04-physical-platform.md).

## Raw notes

