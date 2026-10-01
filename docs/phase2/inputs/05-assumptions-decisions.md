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

### A-1: Fair-weather-only operation

- **Why we believe it:** Stated directly as an operating assumption —
  the rover is not expected to operate in heavy rain or precipitation,
  but should tolerate a short-term surprise weather event (e.g. brief
  rain) without damage.
- **How to verify:** Confirm PLT-3 (waterproofing/dustproofing) design
  meets a "survive brief exposure" bar rather than full waterproofing;
  define shelter points in the map (CAP-3) the rover can reach if caught
  out.

## Decisions already made

### D-1: Cellular out of scope for Version 2

- **Decision:** Cellular communications are out of scope for this
  version.
- **Reason:** Cost and SIM/plan overhead; a self-hosted legacy 1G/2G
  private network was considered but explicitly deferred beyond this
  phase.

### D-2: Mission package sequencing

- **Decision:** Build/sequence mission packages 1 (Map/Detect), 2
  (Track Chickens/Cats), and 3 (Fetch and Retrieve) first, under a
  daytime-only assumption; mission package 4 (Sentry Mode) follows and
  requires nighttime operation.
- **Reason:** Reduces initial complexity — defers night-specific sensing/
  power questions (see Q-4) until the daytime capability set is working.

### D-3: Easy battery access required

- **Decision:** Require easy, minimal-tool battery access (sliding
  panels, etc.) for quick changeouts.
- **Reason:** Operational convenience — avoid a "major effort" every
  time batteries need swapping.

### D-4: Adopt "Bingo Fuel" concept

- **Decision:** The rover tracks battery voltage/consumption against
  distance-from-home and autonomously returns at an optimal speed once
  the reserve threshold is crossed, reporting the event via telemetry at
  high priority.
- **Reason:** Naval-aviation-inspired safety margin; ensures the rover
  doesn't strand itself out of power. MP-3 additionally needs a
  pre-mission power-reserve check that allows for the weight of a
  carried item.

### D-5: Defer home/base charging station

- **Decision:** Defer the home/base charging + map-data-offload station
  concept beyond Phase 2.
- **Reason:** Explicitly called out as "nice to have… not required for
  V1" — adds scope without being necessary for the core mission
  packages.

### D-6: Core compute architecture — hybrid Pi + ESP32, Pi owns sensing

- **Decision:** Hybrid architecture (was Q-1 option c): Raspberry Pi
  runs mission logic and owns all sensing (GPS, IMU, ultrasonic,
  camera); ESP32 stays scoped to drive-train actuation, bump-safety
  interrupt, drive-status reporting, geofence push, and OTA. Pi AI
  Camera confirmed for SEN-3, connected via the Pi's own CSI port (not
  the ESP32).
- **Reason:** This is already what the merged `papaya_mission` software
  assumes — `SensorHub` (gps/imu/ultrasonic/camera) is Pi-side, and
  `Esp32Link` is deliberately scoped to bump/drive/geofence/OTA with no
  sensor-read methods. Confirming it as an explicit decision avoids
  re-litigating it, and keeps the Pi↔ESP32 link from growing new
  message types (e.g. ultrasonic-over-UART) it doesn't need.
- **"OTA" and "geofence push" clarified (2026-09-30):** both are local
  Pi→ESP32 messages over the existing serial link, never independent
  ESP32 networking. OTA: the Pi downloads new ESP32 firmware over its
  own WiFi, then flashes the ESP32 locally (esptool-class serial
  flashing) — "the Pi acts as the flash relay," per the original MP-1
  design spec. Geofence push (`send_geofence_update`): defined in the
  `Esp32Link` interface but never called by `MissionRuntime` yet, and
  its exact purpose isn't documented — the ESP32 has no GPS, so it
  can't enforce a boundary itself; candidates are a local status-LED
  indicator (GPIO48, see CON-B2) or a future redundant-safety hook.
  Leave as an open question for the ESP32 firmware plan.
- **Pi model (2026-09-30):** Raspberry Pi 5, 4GB or 8GB (both on hand,
  8GB likely used — this workload doesn't obviously need 8GB, so 4GB
  stays an option). NVMe HAT available to avoid SD-card wear. Not a
  breadboard blocker either way — GPS/IMU/ultrasonic/camera use standard
  interfaces (UART/I2C/CSI) present on every Pi model, and Pi 5's RP1
  chip in particular makes extra UARTs easy to enable via device-tree
  overlays if GPS and a Pi↔ESP32 UART link ever needed to coexist.

## Open questions

These become the agenda for the design session.

### ~~Q-1: Core compute architecture~~ — answered, see D-6

### Q-2: LiDAR usage pattern

- **Options considered:** Full-time LiDAR for mapping; reduced-
  frequency LiDAR for general (non-mapping) use to limit power draw;
  ultrasonic-only outside of dedicated mapping runs.
- **Leaning:** Primary value seen in the mapping mission (MP-1);
  general-use case still open.
- **Blocks:** SEN-2, CAP-9, power budget.

### Q-3: Coordinate system

- **Options considered:** Full lat/long throughout; GPS for initial
  mapping only, converted to a local integer (x,y) system maintained
  onboard via fixed waypoints and bearing/distance; an (x,y) overlay on
  top of GPS (used for fixed obstacle-type areas); What3Words as an
  additional location-identifier layer for ad hoc Fetch and Retrieve
  delivery points, if available without expensive licensing.
- **Leaning:** An (x,y) overlay on top of GPS, plus a possible
  What3Words layer for Fetch/Retrieve.
- **Blocks:** CAP-2, CAP-3, CAP-4 (position fields), MP-3.

### Q-4: Sentry Mode night-sensing package

- **Options considered:** Reuse daytime sensor suite as-is; add a
  dedicated IR camera/sensors; deploy a separate, lower-power sensor
  package specifically for night sweeps.
- **Leaning:** Not stated — open.
- **Blocks:** MP-4, SEN-3, night-time power budget.

### Q-5: Additional power measurement points

- **Options considered:** Per-motor/per-servo measurement points; per-
  sensor; per-rail (5V logic / 6V servo).
- **Leaning:** Not stated — open.
- **Blocks:** PWR-2, CAP-4.

### Q-6: Antenna integration

- **Options considered:** Consolidate ELRS/LoRa/WiFi/GPS antennas onto a
  single common mast (possibly shared with the sensor mast, PLT-2); keep
  as a separate "nest" of individual antennas.
- **Confirmed constraint (2026-09-30):** these cannot share antennas —
  GPS (L1 band, ~1575 MHz), LoRa (915 MHz ISM), and ELRS are on distinct
  frequencies, each requiring its own correctly-tuned antenna; WiFi is
  typically on-module (2.4/5 GHz, no external antenna in most Pi/ESP32
  setups). So this is genuinely "at least 3 distinct antennas," not a
  single-feedline question — raises the stakes of consolidate-vs-nest
  rather than resolving it.
- **On-hand parts:** Wishiot 915 MHz 5dBi antennas (large fixed plastic
  housing, SMA-ish screw-terminal coax pigtail) for LoRa; 2x ELRS
  antennas from the V1 design. **Gap:** no GPS-specific active antenna
  yet identified — the chosen SparkFun NEO-M9N SMA board expects an
  external antenna (no onboard patch), so one needs sourcing before the
  breadboard can get a real fix, independent of this mast question.
- **Leaning:** Not stated — open.
- **Blocks:** PLT-2, COM items, PCB/wiring impact.

### Q-7: Solar charging assist

- **Options considered:** No solar; partial solar sized to sustain
  control electronics/radios only (not motors/servos).
- **Leaning:** "Nice to have," not essential — would meaningfully
  increase autonomy if pursued.
- **Blocks:** PWR-3.

### Q-8: Battery consumption model for Bingo Fuel

- **Options considered:** Collect field telemetry during early MP-1
  mapping runs and derive the model after the fact (accepting the
  capability won't be real-time-accurate at first); build a simplified
  model up front and refine later.
- **Leaning:** Collect data during MP-1 runs first; refine over time.
- **Blocks:** D-4, CAP-11.

## Raw notes

