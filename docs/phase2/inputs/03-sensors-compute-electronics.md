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
  corners.
- **Mounting needs:** Corner-mounted, low to the ground (to catch
  obstacles below the height of ultrasonic/LiDAR/camera sensing).
- **Notes:** Should give immediate stop-forward-motion feedback; ideally
  integrates with CAP-9 to interrupt the current path and back away/
  reroute around the detected object.

### SEN-5: IMU (Inertial Measurement Unit)

- **Supports:** CAP-9, CAP-3
- **Candidates:** Not yet specified at the exact-SKU level, but the
  interface class is settled: I2C (4-wire, shares a bus trivially with
  other I2C devices — near-zero pinout risk). Lean toward a 9-DOF part
  with a magnetometer (MPU-9250/ICM-20948-class, or BNO055 for onboard
  sensor fusion) rather than a bare 6-DOF accel/gyro-only part (e.g.
  MPU-6050), since `papaya_mission.position_fusion.ImuReading.heading_deg`
  is a compass heading, which a 6-DOF part can't directly provide.
  Exact SKU deferred — not a breadboard blocker.
- **Interface/owner (see D-6):** Pi-managed, I2C.
- **Mounting needs:** TBD.
- **Notes:** Optional/desired — useful for orientation but not required
  if it meaningfully complicates the architecture or power budget.

### SEN-6: GPS

- **Supports:** CAP-2, CAP-3, CAP-11, CAP-4
- **Candidates:** Not yet specified at the exact-SKU level, but the
  interface class is settled: UART/NMEA-0183 (4-wire — near-zero pinout
  risk). u-blox NEO-family (NEO-6M/7M/8M/M9N/M10) is the de facto hobby/
  prosumer standard, consistent pinout across the family, heavily
  documented. Exact SKU deferred — not a breadboard blocker. One
  non-blocking wrinkle: if the still-undecided Pi↔ESP32 link also wants
  UART and the chosen Pi model exposes only one hardware UART, GPS may
  need a USB-to-serial adapter instead of header pins — a trivial,
  common workaround.
- **Interface/owner (see D-6):** Pi-managed, UART.
- **Decimeter-accuracy target may be stricter than actually needed** —
  worth checking against `position_fusion.py`'s existing dead-reckoning
  error budget (`GPS_LOSS_MAX_ERROR_RADIUS_M = 5.0` in the Mission
  Runtime code already tolerates several meters of drift between fixes)
  before shopping for RTK-class hardware to hit decimeter accuracy.
- **Mounting needs:** Antenna integration TBD (see Q-6 in 05).
- **Notes:** Almost certainly mandatory. Update frequency can be
  moderate — rover is low-speed, so a few fixes per minute is likely
  sufficient.

## Compute

Where does the thinking happen? The ESP32-S3 alone, the ESP32 plus a
companion computer (Raspberry Pi, Jetson, etc.), or offboard (laptop over
WiFi)? Capture leanings and reasons, even if undecided.

### CMP-1: Core platform architecture

- **Supports:** CAP-8, CAP-9, CAP-3, all missions
- **Decided (D-6):** Hybrid — Pi runs mission logic and owns all
  sensing (GPS/IMU/ultrasonic/camera); ESP32 stays scoped to drive-train
  actuation, bump-safety interrupt, drive-status, geofence, and OTA.
  Which specific Pi model (Pi 5 / Zero 2W / other) remains open, but
  doesn't block the breadboard — see D-6 in
  [`05-assumptions-decisions.md`](05-assumptions-decisions.md).

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

- **Notes:** High bandwidth, limited range; suitable for local/on-
  premise hosting; assumed available from either the ESP32 or Pi
  platform.

### COM-2: LoRa / LoRaWAN

- **Notes:** Long-range, low-power; for basic telemetry and low-
  bandwidth commands; not suitable for large data transfers (e.g.
  images/maps).

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

