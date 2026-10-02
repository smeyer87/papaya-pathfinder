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

### A-2: Mild, mostly-flat farm terrain; major hazards geofenced out

- **Why we believe it:** Stated directly 2026-10-02 as an operating
  assumption — the farm terrain is "flat" by human standards (no major
  hills, ditches, etc.); anything significant gets placed in a geofence
  exclusion zone (CAP-3) rather than designed around mechanically.
  Target operating condition is "human walking pace" over mildly uneven
  ground, including washboarding, while performing obstacle detection/
  tracking missions — not high-speed off-road use, and not the abuse
  profile hobby off-road RC trucks are built to survive.
- **How to verify:** Confirms the suspension spec for PLT-7 (modest
  travel, soft spring rate — damping frequent small washboard impulses
  at low speed, not hard impacts) and informs Q-11's leaning (small
  disagreement between independent front/rear differentials at this
  terrain scale may not need a dedicated chassis torsion joint). Also
  the reason the existing pin failures count as a "Must fix," not an
  edge case — they're already occurring inside this normal operating
  envelope, not a worse one.

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

### D-7: Weight-budget-by-height for the enlarged payload bay

- **Decision:** In the redesigned (substantially larger) payload bay,
  keep the heaviest single component — almost certainly the battery —
  as low and as centered (both fore-aft and side-to-side) as the bay
  allows. Use the *added* height/length/width for lighter components
  (wiring, LCD, ESP32, antennas).
- **Reason:** The bay is growing enough (PLT-5: minimum +6–9" length,
  +3–5" height/depth, proportional width) to meaningfully raise and
  shift center of gravity versus today's nominal CoG — a taller/longer
  box risks worse rollover stability on slopes/turns and an unbalanced
  fore-aft shift if mass isn't placed deliberately. This guideline holds
  regardless of how Q-9 (6-vs-8-wheel) resolves, so it's logged as a
  decision rather than left open.

### D-8: Steered wheel position within each 2×2 axle pair (if Q-9 → 8-wheel)

- **Decision:** If Q-9 resolves toward 8 wheels (two independent 2-wheel
  pivot pairs per side, front and rear), the steering servo stays on the
  **outer** wheel of each pair — the front-most wheel of the front pair,
  the rear-most wheel of the rear pair — i.e. whichever end sits at the
  true chassis corner, same as today. The inner wheel of each pair
  (closer to the chassis center) is drive-only, not steered.
- **Reason:** This isn't a new load case — the current 6-wheel design's
  rear "pair" (middle wheel + rear corner wheel) already has exactly
  this shape: the outer member (rear corner) is steered, the inner
  member (middle) isn't. Extending the same pattern to the front
  preserves the existing 4-corner independent-steer geometry that gives
  the rover its tight turning today. Turning tightness comes from
  coordinating each corner's steer angle (plus skid-steer differential)
  relative to the turn center, not from wheelbase length, so the longer
  wheelbase from PLT-5's bay growth doesn't cap how tight the rover can
  turn — it does mean the steering-angle/trim mapping needs
  re-deriving for the new corner-to-corner distances once real
  dimensions are set, the same category of work as the `TRIM_LF/RF/LB/RB`
  re-zero already done once for the DS3218 horns (`CHANGELOG.md`
  v1.0.0) — expected follow-on work, not a new risk.
- **Watch for PLT-7:** the outer-wheel-steered pattern puts more
  cornering-load leverage on that pair's pivot bracket than a wheel
  mounted directly at a main chassis pivot. Already true of today's rear
  bogie, so it's a known load case to design against, not an unknown
  one — but the suspension design should account for it explicitly.

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

### Q-9: 6-wheel vs 8-wheel drivetrain

- **Options considered:** Keep the current 6-wheel rocker-bogie layout
  (3 wheels/side, 4 corner steering servos, suspension/strain fix
  applied to the existing axles — PLT-7); expand to 8 wheels as two
  independent 2×2 axle pairs per side, pivoting at front and rear mount
  points on the payload bay, keeping the same 4 corner steering servos
  and adding one DC drive motor per side (2 new motors total), plus the
  added battery load those motors draw.
- **Leaning (updated 2026-10-02):** Leaning toward 8-wheel. The real
  driver turns out not to be the servo-connector-strain problem (PLT-7
  needs fixing either way, independent of wheel count) but the bay-size
  growth itself (PLT-5): the existing design is one 3-wheel bogie arm
  per side, sized for the current wheelbase — it has no "stretch" left
  once the bay grows a confirmed minimum of 6–9" longer. Two independent
  2×2 pivot pairs (front/rear) let the wheelbase scale with the longer
  bay while repositioning wheels to distribute load evenly fore-aft (and
  side-to-side, if the stance also widens) — something the current
  single-arm geometry can't do by just stretching. Electrically close to
  free: confirmed 2026-10-02 the current 6 motors are already ganged
  3-per-side onto a single BTS7960 H-bridge channel per side
  (`pathfinder-autonomous/README.md`), so a 4th motor per side can gang
  onto the same existing channel — no new GPIO/`CON-B2` conflict,
  pending a check that each BTS7960 can handle 4 motors' combined stall
  current instead of 3.
- **Blocks:** PLT-7 (axle/suspension design, co-designed with this, not
  sequenced before it), PLT-8/Q-10 (very likely needs a second rear
  transverse link, not just "possibly" — see Q-10), PLT-9 (CoG/stance
  tradeoff), power budget (PWR items, D-4 Bingo Fuel model).

### Q-10: Second rear transverse pivot link (depends on Q-9)

- **Options considered:** A single transverse link, as today, relocated
  underneath the chassis per PLT-8 (sufficient if the 6-wheel layout is
  kept); two transverse links — one per 2×2 axle pair, front and rear —
  each independently equalizing its own pair's wheel contact, if the
  8-wheel option in Q-9 is adopted.
- **Leaning (updated 2026-10-02):** If Q-9 resolves toward 8-wheel as
  two genuinely independent pivot pairs (not one arm spanning all 4
  wheels per side), this is very likely "yes, two links" rather than an
  optional extra — each independently-pivoting pair needs its own
  equalizer to keep the body level, the same reason the single pair
  needs one today. Not yet verified against real geometry.
- **Blocks:** PLT-8.

### Q-11: Chassis torsional compliance with two independent transverse differentials

- **Options considered:** Rely on existing structural give in the
  payload-bay body/mounts to absorb any disagreement between the front
  and rear differentials (no new part); add an explicit torsional pivot
  along the chassis spine — a dedicated rotational joint letting the
  front half and rear half of the body twist relative to each other,
  independent of the per-side fore-aft "pivot"/"bogey" joints and
  separate from the transverse differentials themselves.
- **Why this matters:** Today's single, central transverse differential
  gives one well-determined relationship between left/right rocker angle
  and body roll. Two *independent* differentials (front + rear, per
  Q-9/Q-10) can each separately try to set the body's attitude from
  their own end's ground contact — if they disagree and the chassis is
  perfectly rigid between them, the linkages fight each other instead of
  both doing their terrain-following job, which risks a wheel losing
  ground contact or extra stress dumped into the mounting hardware.
- **Leaning:** Not stated — open, but A-2's mild-terrain assumption
  (small washboard bumps mean small disagreement between the two ends)
  suggests trying the no-new-part option first; this is a "build it and
  see if it binds" question better answered by physical testing once
  both transverse links exist than by analysis alone.
- **Blocks:** PLT-8, Q-10.

## Raw notes

