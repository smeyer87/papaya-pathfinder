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
- **Candidates:** Not yet specified.
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
- **Mounting needs:** TBD.
- **Notes:** High priority — some form of camera is required in all
  scenarios. The Pi AI Camera's edge-classification capability is a key
  factor pulling the platform toward a Raspberry Pi / hybrid controller
  design (see CMP-1, Q-1 in 05).

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
- **Candidates:** Not yet specified.
- **Mounting needs:** TBD.
- **Notes:** Optional/desired — useful for orientation but not required
  if it meaningfully complicates the architecture or power budget.

### SEN-6: GPS

- **Supports:** CAP-2, CAP-3, CAP-11, CAP-4
- **Candidates:** Not yet specified — need decimeter-level accuracy.
- **Mounting needs:** Antenna integration TBD (see Q-6 in 05).
- **Notes:** Almost certainly mandatory. Target accuracy ~decimeter
  level for reliable position/object-avoidance. Update frequency can be
  moderate — rover is low-speed, so a few fixes per minute is likely
  sufficient.

## Compute

Where does the thinking happen? The ESP32-S3 alone, the ESP32 plus a
companion computer (Raspberry Pi, Jetson, etc.), or offboard (laptop over
WiFi)? Capture leanings and reasons, even if undecided.

### CMP-1: Core platform architecture

- **Supports:** CAP-8, CAP-9, CAP-3, all missions
- **Notes:** Open decision between (a) staying ESP32-based — low power,
  easy analog/digital integration, matches current baseline; (b)
  shifting to Raspberry Pi — better integration with the AI camera and
  advanced capabilities, at higher power/space cost; if Pi, further
  choice between Pi 5 (most capable, NVMe support, higher power/space),
  Pi Zero 2W (lower power, less capable), or Pi Pico 2W (roughly
  ESP32-equivalent — only useful as part of a true multi-device split);
  or (c) hybrid — Pi as master/mission-logic controller delegating
  sensor collection to ESP32. See Q-1 in
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

