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

  **Drive-motor weatherproofing, raised 2026-10-02:** the DC motor sits
  at wheel-axle level today, so its electrical connection is also at
  ground level — exposed to wet grass/dew (not puddles/active rain,
  per `A-1`). Two options raised: a cap over the exposed wire-exit end
  (simple, works on the current rigid strut, good as a near-term
  interim fix); or redesigning the motor housing to sit fully enclosed
  within the printed strut, with wiring routed internally rather than
  exiting low near the ground. Leaning toward the full-enclosure option
  as the long-term answer, specifically because PLT-7 is already
  converting this exact strut from a rigid single-pin joint into a
  knuckle+arm assembly — doing the motor enclosure and internal wire
  routing (PLT-4) in that same rebuild avoids reworking the part twice,
  and a full enclosure protects the whole motor can, not just the wire
  exit point. Explicitly ruled out: adding an intermediary axle/transfer
  gear to relocate the motor away from wheel level — too much added
  complexity for the weatherproofing benefit gained.

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
- **Notes:** **Conflict confirmed (2026-10-02):** the Phase 2 sensor/
  compute footprint (Pi 5, ESP32, GPS, IMU, LCD, wiring per
  `03-sensors-compute-electronics.md`) and the goal of fully enclosing
  the bay for environmental isolation (PLT-3) don't both fit in the
  current bay as-is — this is now a real space conflict, not just "needs
  to be a bit bigger." Two mechanical items raised alongside this
  directly affect how much room a redesigned bay has to work with: PLT-7
  (axle/suspension changes may add bay-adjacent structure) and PLT-8
  (relocating the top-mounted transverse link frees usable top-of-bay
  space for enclosure, which may ease this conflict more than growing
  the box footprint itself).

  **Scale and vision (2026-10-02):** the growth needed is substantial,
  not incremental — a rough minimum of +6–9" in length, +3–5" in
  height/depth, and a proportional increase in width (the 3 dimensions
  can trade off against each other — shorter/fatter/taller variants are
  all open — but not shrink below this combined volume). Vision for the
  bay itself: an open top (no internal bracing in the way), covered by a
  sliding or PC-case-style thumbscrew panel, enclosing everything
  currently mounted exposed today (servos, motor ends, wiring
  distribution). A box this much larger raises a center-of-gravity
  question independent of the wheel-count question — see new PLT-9.

  **Current-prototype ground truth, not in any repo STL/STEP
  (2026-10-02):** custom parts already exist that the base CAD files
  don't show. A battery compartment has been added underneath the
  existing payload bay (today's working prototype: open at the front,
  held with a rubber band; intended final form: a proper removable front
  panel, positioned for easy cable-disconnect and slide-out access). A
  bolt-on front input wiring distribution exists ahead of the main
  distribution panel: battery junction, fuse, master power switch, and
  input terminal block — the battery cable joins this before reaching
  the main input distribution. Further internal payload-bay
  organization (3D-printed spacers/mounts for the BTS7960 units, PCB
  mount, etc., so components aren't just crammed in loose) is planned
  but not yet designed. Any future bay-size/layout work needs to account
  for these as existing fixed points, not design from a blank box.

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

### PLT-7: Axle/wheel suspension (printed steering-pivot pin failure)

- **Supports:** PLT-5 (added weight from internalized electronics),
  overall drivetrain durability
- **Priority:** Must
- **Description:** Known current-state problem, raised 2026-10-02.
  **Correction (2026-10-02, same day):** originally described as "servo
  connector pins breaking" — initially misread as an electrical wiring
  connector. The real failure is mechanical: on each corner (steered)
  wheel, the wheel+motor strut attaches to the fixed, pivot-mounted servo
  only through one small 3D-printed part (the "servo horn adapter")
  and a cross-bolt through its pin. That one pin currently has to carry
  three different loads at once — steering torque from the servo, the
  wheel's full structural weight, and 100% of every ground-impact shock,
  since there is no suspension travel anywhere in the strut today. It's
  a stress-concentrated, layer-line-weak point (cross-drilled hole in a
  thin printed shaft) asked to do a structural job it was never sized
  for. Two failure modes observed: the pin shears outright (~90%+ of
  failures, catastrophic — the whole wheel+motor strut separates from
  the rover and it's undrivable), or the servo's own output spline slips
  loose from its horn under the same undamped shock (degraded but still
  drivable — that corner free-wheels/drags). The added weight from
  Phase 2 sensors/compute (PLT-5) is expected to compound both.
- **Diagnosis/approach (2026-10-02):** the fix isn't "add a shock
  in-line with what exists" — today's pin provides a steering *rotation*
  axis, not a vertical *suspension-travel* axis, so real shock absorption
  needs a genuinely new degree of freedom. The proven pattern from hobby
  RC front-ends: separate the steering-torque path from the
  structural/impact-load path entirely. A new, robust (likely metal)
  suspension arm pivots at the chassis/pivot part and carries the
  wheel+motor's full weight and impact load, with the shock absorber
  spanning from that arm to a fixed chassis point; the servo stays
  chassis/pivot-fixed and drives the wheel's steering angle through a
  tie rod (ball-jointed at both ends) that can follow the arm's vertical
  arc, rather than direct-driving the strut rigidly as today. This
  should address both failure modes: the printed horn adapter goes back
  to carrying only steering-positioning torque (its intended job, at a
  fraction of today's load), and the servo's own shaft stops seeing raw
  impact shock either. Scale note: the comparison part the user
  originally pulled (INJORA 40mm big-bore shock) is sized for the SCX24
  (1/24 scale) — too small for this rover's DS3218/GA25-class hardware;
  1/10-scale big-bore shocks (the Traxxas/Associated/Axial aftermarket
  category) are the right size class once real geometry is set.
  **Operating envelope confirmed 2026-10-02 (A-2):** this rover targets
  human-walking-pace travel over mild, mostly-flat farm terrain with
  washboarding, not off-road-abuse-grade impacts — major hazards get
  geofenced out rather than designed around. That favors a soft spring
  rate and modest travel (damping frequent small impulses at low speed)
  over a heavy-duty, long-travel part, lowering cost/complexity risk on
  the shock itself even though the knuckle/tie-rod architecture change
  around it is unchanged. Also means these pin failures are already
  happening inside normal operating conditions, not an edge case — this
  stays a "Must," not a nice-to-have.
  Cheap, parallel-track experiments on the current design, independent
  of the bigger rebuild: the CF-nylon filament trial already in
  progress (nylon's impact toughness/layer adhesion should beat PLA/
  PETG at this exact snap), and a metal pin/sleeve reinforcing the
  cross-bolt hole as a stop-gap. Needs mechanical research/prototyping
  against the existing corner-wheel geometry
  (`pathfinder/3d-models/arm_left.stl`/`arm_right.stl`,
  `pivot_left.stl`/`pivot_right.stl`, `motor_mount.stl`); final design
  depends on wheel count/loading, see Q-9.
- **Notes:** Coupled to, but not solved by, the 6-vs-8-wheel decision
  (Q-9 in [`05-assumptions-decisions.md`](05-assumptions-decisions.md)):
  more wheels doesn't reduce the shock a wheel transmits on impact, so
  this suspension fix is needed regardless of which way Q-9 resolves.
  **Clarified 2026-10-02:** Q-9 turns out to be driven by a separate,
  independent cause (the enlarged bay's length — see PLT-5's "Scale and
  vision" note and Q-9), not by this strain problem — the two should be
  designed together anyway, since an 8-wheel layout changes per-wheel
  load and where each wheel sits relative to its strut, both direct
  inputs to this suspension design.

### PLT-8: Transverse pivot link (rocker-bogie differential) relocation

- **Supports:** PLT-5, PLT-3 (enclosure clearance)
- **Priority:** Should
- **Description:** The existing transverse pivot-link assembly
  (`pathfinder/3d-models/differential_bar.stl`,
  `differential_link_left.stl`/`differential_link_right.stl`) connects
  the left and right 3-wheel rocker assemblies, giving each side some
  independent motion over uneven ground. It currently sits on top of the
  payload bay, directly interfering with the PLT-3/PLT-5 goal of a fully
  enclosed bay. Raised 2026-10-02: can this assembly move underneath the
  chassis instead, clearing the top-side interference?
- **Approach:** TBD — needs a clearance/geometry pass against
  `body.stl` and the full assembly in
  [`../../../pathfinder/cad/papaya-pathfinder.step`](../../../pathfinder/cad/papaya-pathfinder.step)
  (ground clearance impact of moving the pivot linkage below the body is
  the main open risk).
- **Notes:** If the 6-vs-8-wheel question (Q-9) resolves toward 8
  wheels, a second (rear) transverse link may be needed in addition to
  relocating this one — see Q-10.

  **Pivot-point reasoning (2026-10-02, not yet verified against the real
  geometry):** a rocker-bogie arm's own chassis-mount pivot (where the
  arm bolts to the body) and the differential/equalizer linkage that
  cross-connects left and right arms are mechanically distinct. Moving
  the equalizer underneath doesn't necessarily require moving the arm's
  own pivot — the arm can keep its current mount point while the
  equalizer reroutes via a bellcrank/pushrod to carry the counter-
  rotation signal underneath instead of across the top. That likely adds
  a couple of small linkage joints, but they carry only body-leveling
  torque, not wheel-impact loads, so they're much lighter-duty than the
  PLT-7 strut/servo-connector problem. The unresolved risk is ground
  clearance at the linkage's lowest point of travel, now that it runs
  underneath instead of on top — this is the clearance pass already
  called out above, not yet done.

### PLT-9: Center of gravity / weight budgeting for the enlarged bay

- **Supports:** PLT-5, general stability/rollover safety
- **Priority:** Must
- **Description:** PLT-5's enlarged bay (substantially taller/deeper and
  longer, see its "Scale and vision" note) raises center-of-gravity risk
  independent of the wheel-count question: more height raises CoG
  (worse for rollover on slopes/turns); more length risks a fore-aft CoG
  shift if the added mass isn't balanced. Raised 2026-10-02.
- **Approach:** Weight-budgeting-by-height guideline: keep the heaviest
  single component (almost certainly the battery) as low and as
  centered — both fore-aft and side-to-side — as the redesigned bay
  allows; use the *added* height/length for lighter components (wiring,
  LCD, ESP32, antennas). Applies regardless of how Q-9 (6-vs-8-wheel)
  resolves.
- **Notes:** If Q-9 resolves toward 8 wheels with a wider stance (not
  just a longer wheelbase), the wider support base would help offset a
  raised CoG — worth factoring in when the axle-pair geometry is
  designed.

## Raw notes

- **(2026-10-02) CAD-review capability note:** Claude can view rendered
  raster images (`.png`, e.g. `pathfinder/cad/model.png`,
  `pathfinder/schematics/*.png`) directly, but cannot visually interpret
  raw `.stl`/`.step` 3D geometry files the way a CAD viewer would — no
  rendering tool is available for those formats. Useful review input for
  mechanical discussions is therefore: existing rendered PNGs, this
  file's/the spec's written descriptions, and the STL/STEP files' own
  names/structure (which components exist, roughly how they're named) —
  not a visual critique of the actual 3D shapes. `model.png` (viewed
  2026-10-02) confirms the 6-wheel rocker-bogie layout, 4 corner wheel
  struts with servo housings, and the top-mounted transverse linkage bar
  described in PLT-8.

