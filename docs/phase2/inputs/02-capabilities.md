# 02 — Capabilities

Logical abilities the rover needs to carry out the missions in
[`01-missions.md`](01-missions.md). Stay hardware-agnostic where you can —
"detect obstacles within 1 m ahead" rather than "use an ultrasonic sensor".

Phase 1 baseline capabilities (already exist, no need to list): manual
drive via ELRS — steering, throttle with expo + 0.6 speed cap,
spin-in-place.

## Capabilities

<!-- Copy this block per capability. Useful groupings to prompt your
thinking: perception, localization/mapping, navigation/planning, motion
control, safety, telemetry/operator interface, payload/tooling, data
logging. -->

### CAP-1: Management UI

- **Supports:** MP-1, MP-2, MP-3, MP-4, CAP-2, CAP-7
- **Priority:** Must
- **Description:** Shared UI to pass information between the master
  controller system and the rover(s). Candidates: a cloud-hosted UI, or
  a local container-hosted UI run on a host computer. Used for geofence
  drawing (Google Maps overlay, CAP-2), Fetch/Retrieve status updates
  (MP-3), and remote/mission command issuance (CAP-7).
- **Performance target** (range, accuracy, rate, latency — rough is fine):
  n/a — requirements will evolve.
- **Interaction with manual control:** n/a — separate from the ELRS
  manual-control path.
- **Notes:** —

### CAP-2: Geofence Management

- **Supports:** MP-1, MP-2, MP-3, MP-4
- **Priority:** Must
- **Description:** Define boundaries where the rover can/cannot operate.
  Inclusive fences = rover must stay inside; exclusive fences = rover
  must not enter. Fences are layered — e.g. one master inclusive
  operating boundary containing multiple exclusive "danger" zones.
  Fences are drawn on a Google Maps overlay in the Management UI
  (CAP-1). Alternative/backup capture mode: manually drive the rover
  (via ELRS) along the desired boundary and upload the captured track on
  command.
- **Performance target:** n/a
- **Interaction with manual control:** Manual-drive boundary-capture
  mode is an explicit intended use of ELRS control.
- **Notes:** If the rover finds itself inside an exclusion zone it
  should stop and alert; behavior may be configurable by depth of
  intrusion — e.g. under one rover-length and easily reversible could
  auto-recover, otherwise stop and wait for help (ties to CAP-12).
  Assumes GPS (SEN-6); may convert GPS fixes to a local onboard (x,y)
  system using fixed waypoints/bearing/distance from landmarks if
  running GPS continuously is too power-intensive (see Q-3).

### CAP-3: Map Development and Storage

- **Supports:** MP-1, MP-2, MP-3
- **Priority:** Must
- **Description:** Store maps onboard in a rover-efficient format;
  support map segmentation into operating sectors so only the active
  sector's detailed map need be resident in memory (load the adjacent
  sector as the rover approaches a sector boundary). Support map updates
  from ongoing operations, but permanent changes require human review
  before being committed, to avoid corrupting the map from a temporary
  condition or sensor error. Newly discovered obstacles/map data from
  any mission should be appended to the master map.
- **Performance target:** n/a
- **Interaction with manual control:** n/a
- **Notes:** May need to store designated "shelter" points (see A-1)
  alongside obstacle data.

### CAP-4: Telemetry Reporting

- **Supports:** MP-1, MP-2, MP-3, MP-4 (core, cross-cutting)
- **Priority:** Must
- **Description:** Core requirement — the rover must report telemetry to
  a remote server (on-prem/container-hosted or cloud). Fields expected
  at minimum:
  - Rover ID (multi-rover support)
  - Time (UTC + local-timezone offset; UI always displays local time)
  - Position — GPS lat/long (5–6 decimals?) and/or local (x,y); altitude
    optional if easily available, not required
  - Power levels on all supplies/batteries; current draw at all
    measurement points (down to individual motor/servo/sensor if
    feasible)
  - Internal payload-bay temperature; external temperature, light
    level, humidity/other environmental sensors as added
  - GPS fix/status: position, HDOP/VDOP, satellite count
  - Motor speeds/positions (wheel speed, steering angle, etc.)
  - Sensor status/error flags for all sensors
  - Onboard processor load and memory usage
  - Comms status: WiFi signal strength, cellular (n/a — out of scope,
    see D-1), estimated ELRS range from signal strength, LoRa status
  - Navigation status: current mode (Manual/Cruise/Explore/Fetch/
    Sentry/etc.), distance to next waypoint, distance to exclusion
    boundary (if inside one), distance to target
  - Mission status: current mission, phase, phase progress
  - Error/event logs: errors, warnings, alerts, user commands
- **Performance target:** n/a (to be refined)
- **Interaction with manual control:** Navigation-status field must
  reflect Manual mode when under ELRS control.
- **Notes:** —

### CAP-5: Communication Systems — Rover to Host

- **Supports:** CAP-4, CAP-1, CAP-7
- **Priority:** Must
- **Description:** Robust link(s) to carry telemetry out and commands
  in. Leaning toward a hybrid: a long-range/low-power link (LoRaWAN or
  similar) for basic telemetry and low-bandwidth commands, plus WiFi
  for higher-bandwidth data such as images or maps. See
  [`03-sensors-compute-electronics.md`](03-sensors-compute-electronics.md)
  COM items for specific protocol candidates.
- **Performance target:** WiFi = high bandwidth/limited range (local/
  on-prem hosting); LoRa = long range/low bandwidth.
- **Interaction with manual control:** n/a — separate from the ELRS
  manual-control link.
- **Notes:** Cellular is explicitly out of scope for this version (see
  D-1).

### CAP-6: Power Management (system-level)

- **Supports:** MP-1, MP-2, MP-3, MP-4, CAP-4, CAP-11
- **Priority:** Must
- **Description:** Define an overall power budget; support multiple
  power sources/rails with a modular power-distribution approach; build
  in redundancy/fail-safes; manage recharging ergonomics (battery
  access/removal). See
  [`03-sensors-compute-electronics.md`](03-sensors-compute-electronics.md)
  PWR items for measurement points/hardware, and
  [`04-physical-platform.md`](04-physical-platform.md) PLT items for
  physical battery-access design.
- **Performance target:** n/a
- **Interaction with manual control:** n/a
- **Notes:** —

### CAP-7: Remote Operation

- **Supports:** MP-1, MP-2, MP-3, MP-4
- **Priority:** Must
- **Description:** Allow remote operation of the rover via a UI (CAP-1);
  support both direct control (manual, via ELRS) and indirect control
  (mission-level commands). Define the control hierarchy (master
  controller system vs. remote users). Rover is expected to primarily
  operate in remote/autonomous mode, accepting mission commands as
  needed.
- **Performance target:** n/a
- **Interaction with manual control:** Manual ELRS control is
  positioned as backup/recovery, and as the method for driving geofence
  boundary-capture runs (CAP-2). Phase 1 baseline manual control
  (steering/throttle w/ expo + 0.6 speed cap, spin-in-place) already
  exists.
- **Notes:** —

### CAP-8: Basic Object Classification

- **Supports:** MP-2, MP-4, MP-1
- **Priority:** Must
- **Description:** Onboard image detection/classification. Classes:
  humans, chickens, cats, and defined predator animals (raccoon, possum,
  coyote — predator classes only needed for MP-4, typically at night).
  Also farm-object classes: vehicles (mowers, tractors, pickup trucks —
  no large machinery like combines/harvesters) and stationary objects
  (barrels, fence posts, etc.).
- **Performance target:** n/a
- **Interaction with manual control:** n/a
- **Notes:** —

### CAP-9: Object Avoidance

- **Supports:** MP-1, MP-2, MP-3
- **Priority:** Must
- **Description:** Detect obstacles in the path of motion (ultrasonic/
  LiDAR/camera) and plot an avoidance route. Avoidance strategy can vary
  by object type — a potentially mobile object (cat, chicken) may not
  need the same handling as a fixed object (barrel, hose, pipe).
- **Performance target:** n/a
- **Interaction with manual control:** n/a
- **Notes:** —

### CAP-10: Route Planning

- **Supports:** MP-3, MP-1
- **Priority:** Must
- **Description:** Simple point-to-point route from load point to
  delivery point (primarily for Fetch and Retrieve), staying within
  geofences and avoiding exclusion areas. Kept deliberately simple —
  open fields, gentle slopes, no road-network/street-level routing
  needed for Phase 2.
- **Performance target:** n/a
- **Interaction with manual control:** n/a
- **Notes:** —

### CAP-11: 'Go Home' / Recovery

- **Supports:** MP-1, MP-2, MP-3, MP-4
- **Priority:** Must
- **Description:** If the rover becomes unsure of its state, it should
  navigate to a "home" point and await instruction. Multiple home points
  may be defined, generally a sheltered location easy for operators to
  locate. A Go Home command can also be triggered by a low-power
  ("Bingo Fuel") condition.
- **Performance target:** n/a
- **Interaction with manual control:** n/a
- **Notes:** **Bingo Fuel concept** (adopted, see D-4) — the rover
  tracks current voltage/consumption against a reserve ("bingo")
  threshold computed from distance-to-home; at Bingo it ceases the
  current mission and returns at optimal speed, reporting the event via
  telemetry at high priority. MP-3 additionally needs a pre-mission
  check of whether sufficient power reserve exists for the round trip,
  with an allowance factor for the weight of the item being carried
  (exact weight-based draw modeling not required for the initial
  release). The underlying consumption model needs field data collected
  during early MP-1 mapping runs (see Q-8); non-linear voltage behavior
  under load should be accounted for as data permits.

### CAP-12: 'Send Help'

- **Supports:** MP-1, MP-2, MP-3, MP-4
- **Priority:** Must
- **Description:** If the rover becomes immovably stuck and cannot
  navigate free, it issues a 'Send Help' alert to the remote operator,
  including current state/location and other relevant context. Sent at
  the highest available priority and over the greatest-range link
  available.
- **Performance target:** n/a
- **Interaction with manual control:** n/a
- **Notes:** —

## Software & autonomy approach

Notes on *how* capabilities might be implemented in software — frameworks
(e.g. ROS 2, micro-ROS, bare Arduino), onboard vs. offboard processing,
simulation, anything you've read about or want to try.

-

## Raw notes

