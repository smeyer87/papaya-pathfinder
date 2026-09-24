# 04 — Physical Platform Updates

Mechanical changes needed to support the missions, capabilities, and new
hardware in files 01–03. Phase 1 mechanical baseline is the upstream
full-size Pathfinder (rocker-bogie, 6× GA25 drive, 4× DS3218 corner
steering) — see [`../../../pathfinder/3d-models/`](../../../pathfinder/3d-models/).

## Platform changes

<!-- Copy per change. Useful prompts: sensor mounts/masts, electronics bay
space, battery bay/swap, weatherproofing, cable routing, cooling,
bumpers/protection, payload mounts, wheels/tires/traction, drivetrain
upgrades (encoders, stronger motors), mass and center of gravity. -->

### PLT-1: Drive train reuse

- **Supports:** MP-1, MP-2, MP-3, MP-4
- **Priority:** Must
- **Description:** Keep the existing 6-wheel rocker-bogie drive train —
  works well for the expected terrain. Open to a tracked-vehicle
  architecture if ever required, but not believed to add value for
  these missions.
- **Approach:** Reuse existing (no change)
- **Notes:** —

### PLT-2: Rotating mast

- **Supports:** SEN-1, SEN-2, SEN-3, SEN-6, COM items
- **Priority:** Must
- **Description:** A rotating mast to carry cameras, ultrasonic, etc.
  Could double as the antenna mast, or antennas could be mounted
  separately if that proves more efficient.
- **Approach:** TBD
- **Notes:** See Q-6 in
  [`05-assumptions-decisions.md`](05-assumptions-decisions.md) for the
  antenna-consolidation-vs-nest question.

### PLT-3: Waterproofing & dustproofing

- **Supports:** MP-1, MP-2, MP-3, MP-4, A-1
- **Priority:** Should
- **Description:** Rover is expected to operate only in fair weather (no
  heavy rain), but should tolerate light ground moisture (dew, etc.).
  Wheel drive motors currently sit exposed near ground level and need
  some protection. Full waterproofing isn't required, but aim for a high
  degree of dust resistance. Prefer sliding panels or thumb-screw
  fasteners for anything needing frequent access; permanent screws are
  fine for internal mounts that won't need regular access.
- **Approach:** TBD (panel/fastener redesign)
- **Notes:** If the payload bay is enclosed (see PLT-5), fans/vent ports
  will likely be needed for cooling airflow, since the current fully
  open bay doesn't have a heat problem today.

### PLT-4: Wiring enclosures

- **Supports:** MP-1, MP-2, MP-3, MP-4, PLT-3
- **Priority:** Should
- **Description:** Minimize exposed wiring to reduce risk of grounding
  out exposed connections or snagging on vegetation. Wire runs should be
  logical and clearly labeled. Wheel-assembly redesign should route
  motor wires internal to the wheel/axle frame (needs 3D-printing
  experimentation for wire channels). Servos need some form of cap plus
  routed wiring to reduce environmental exposure and snag risk.
- **Approach:** 3D-printed redesign (wheel/axle, servo caps)
- **Notes:** —

### PLT-5: Larger electronics payload bay

- **Supports:** CMP-1, all new SEN/PWR/COM hardware
- **Priority:** Must
- **Description:** Current payload bay is not sufficient for Phase 2 —
  need to internalize components currently mounted externally. Open
  question on how much larger the central box can go (wider/longer/
  taller) before it affects overall physical stability/viability. Should
  incorporate sliding-panel covers and/or thumb-screw fasteners per
  PLT-3.
- **Approach:** TBD — needs stability analysis
- **Notes:** —

### PLT-6: External payload area

- **Supports:** MP-3
- **Priority:** Must
- **Description:** Rover needs to transport small items — a beverage
  (soda can, 20 oz bottle, water container), a tool, gloves, phone,
  firearm, etc. Weight and space limited; no towed trailer or heavier
  payload planned for this release. Recommend a standard-cupholder-
  shaped removable insert as the default, removable to free up space
  for a larger item when needed.
- **Approach:** 3D-printed insert (removable)
- **Notes:** Weight of carried items should factor into the Bingo Fuel
  power-reserve check (see CAP-11 in
  [`02-capabilities.md`](02-capabilities.md), D-4 in
  [`05-assumptions-decisions.md`](05-assumptions-decisions.md)).

## Raw notes

