# ADR 0002: Servo header GND pads are copper-isolated from the ground pour

## Status

Accepted and resolved — 2026-09-20. Short-term fix (bodge wires) was in
place and verified working on the physical boards. The permanent fix
(zone cutouts, see Addendum below) is now applied to
`pathfinder/kicad/papaya-pcb/papaya-pcb.kicad_pcb` and re-verified via DRC
and the point-probe technique that originally found this defect — ready
for fabrication. See Consequences for what still needs doing on any
already-fabricated board.

## Context

During Phase 1 bring-up, all four steering servos (connectors `J9`–`J12`,
schematic refs `J_S1`–`J_S4`) were completely unresponsive — no boot-time
center snap, no response to transmitter input — despite the ELRS link,
motor drive, and the `U1` 6V servo-bus source (measured at `J8`) all
checking out clean. Substitution testing with a known-good spare servo
(voltage-verified safe on the 6V bus) in all four positions ruled out the
DS3218 servo horns and firmware/PWM configuration as the cause.

A resistance check with the ESP32 removed (no power) was decisive: **0 Ω
from `J8`'s positive terminal to every servo `+` pin (good), but infinite
resistance from `J8`'s ground terminal to every servo `GND` pin.** The
servo power/ground connectors were never receiving a ground return, on two
independent physical board instances (the original GPIO15/40-trimmed
rebuild, and a second clean board swapped in after the first was damaged
during probing) — ruling out a one-off assembly defect.

### Root cause, confirmed against the design file

Investigated with KiCad's bundled Python (`pcbnew`), the same headless
verification approach used for the mounting-hole work
(`docs/development-log.md`). Two things were checked, not assumed:

1. **Pad-level zone override.** All four servo `GND` pads still have the
   "Solid" (`FULL`) zone-connection override that `docs/development-log.md`
   records being applied specifically for this servo header cluster (the
   default 0.5mm pad-to-zone clearance was too wide for the 2.54mm pitch).
   This override is intact — not reverted.
2. **Actual filled copper, freshly recomputed.** A from-scratch zone refill
   confirms each `GND` pad's own copper disc (1.7mm pad, 1.0mm drill) is
   part of the `MASTER_GND` zone. But probing outward from each pad center
   in 0.5mm steps on `B.Cu`, **no `MASTER_GND` copper exists within 3–4mm
   of any of the four pads in any direction.** The pad is a solid but fully
   isolated island — not a thin/marginal spoke, a real physical gap. DRC's
   "unconnected items" check does not catch this class of defect: it
   verifies a pad is *assigned* to the zone's net, not that the zone's
   *poured body* actually reaches it with continuous copper. (DRC did
   correctly flag a real, unrelated isolated-copper island near mounting
   hole `H1` — confirming the check isn't blind to islands in general, just
   to this specific "solid-connected pad, adjacent pour absent" shape.)

Tracing further: the nearest genuine `MASTER_GND` copper is 3.5–6mm away
from each pad (varies by pad/direction), but **the straight-line path to it
crosses `6V_POUR` (`/NET_BUS_6V`) copper on `B.Cu`** in every case checked.
The servo header cluster sits inside the 6V pour's territory (expected,
since each header's `PWR` pin needs that net) tightly enough that the `GND`
pin's zone-fill body got boxed in, with the 6V pour's higher fill priority
claiming the copper on all sides before it reaches real ground territory.
This is the same general failure family already documented in
`docs/development-log.md` for this board (starved thermal reliefs, pads
too deep in a competing zone's territory needing manual "escape stub"
traces) — this instance just wasn't caught at the time, most likely because
the servo cluster's later manual reposition (to clear the mounting-hole
corners) moved the pads without a re-check specific to this failure mode.

## Decision

**Short-term (done):** hand-wired ground jumpers from `J8`'s ground
terminal directly to each servo connector's `GND` pin, bypassing the
pour entirely. Verified working — all four servos now respond correctly
to boot-center and live transmitter input.

**Permanent fix (not yet applied to the PCB file):** route an explicit
ground trace from each servo `GND` pad back to a confirmed-good ground
point, **on `F.Cu`, not `B.Cu`** — since `B.Cu` in this local area is
occupied by the 6V pour, a same-layer trace would have to cross it. Because
all four servo header pads are through-hole, they already carry copper on
both layers, so no via is needed at the servo end; the natural target is
`J8`'s ground pad (`OUTN`, already has a proven trace back to
`J7`/`J_GND_MASTER`). `F.Cu` in this region carries only the servo `SIG`
traces (`S1`–`S4`), which a routed path needs to be routed around, not a
power pour — a normal, low-risk interactive routing job.

This was deliberately **not** scripted end-to-end and pushed to the board
file in this session: two of the four paths have a clean, collision-free
route already identified (see below), but the other two need to route
around the `SIG` traces with more geometric judgment than is safe to
guess blindly for a file headed to fab. This is exactly the kind of
task suited to interactive routing in the KiCad GUI, with real-time DRC
feedback, rather than scripted coordinates trusted without a visual pass.

### Addendum (2026-09-19): a simpler fix than originally proposed

Closer measurement (stepping outward from each pad in 0.2mm increments,
not just testing a single offset point) shows the obstruction between each
pad and real ground is a **thin, contiguous strip of `6V_POUR` copper**,
not a sprawling claim on the whole surrounding area — the original
straight-line approach was fine; it just needed the exact strip removed.

| Connector | Direction | `6V_POUR` strip to notch out | Real ground begins |
|---|---|---|---|
| `J9` | up (−Y) | y ≈ 63.9 → 65.9 (~2.0mm) | y ≈ 63.7 |
| `J10` | down (+Y) | y ≈ 76.1 → 78.7 (~2.6mm) | y ≈ 78.9 |
| `J11` | down (+Y) | y ≈ 76.1 → 78.7 (~2.6mm) | y ≈ 78.9 |
| `J12` | up (−Y) | y ≈ 64.0 → 68.4 (~4.4mm) | y ≈ 63.6 |

(all at each pad's own X — 131.5 for `J9`/`J10`, 146.5/146.46 for
`J11`/`J12`.) **Applied 2026-09-20:** a zone cutout was added to the
`6V_POUR` zone's outline on `B.Cu` at each of these four locations (using
KiCad's "Add a Zone Cutout" tool on the existing zone, not a new
independent zone), then zones were refilled. `MASTER_GND`'s lower fill
priority claims the opened strip and connects straight through, all on
`B.Cu` — no layer jump or routing around the `SIG` traces needed.

Re-verified after the fix: `kicad-cli pcb drc --severity-all
--schematic-parity` — 0 violations, unconnected items down from 5 to 1
(the remaining one is the pre-existing, unrelated island near mounting
hole `H1`). Point-probe re-check (the same technique that originally
found this defect) — real `MASTER_GND` copper now reaches within 0.9mm of
all four pads (was: nothing within 3–4mm). `6V_POUR`'s connection to each
header's `PWR` pad was separately confirmed undisturbed. This was simpler
than the F.Cu jumper-trace approach below, which is kept only as a
fallback/reference and was not needed.

### Candidate routing data (fallback approach, F.Cu jumper traces)

All coordinates in mm, board origin as used by the existing `.kicad_pcb`.

| Pad | Position | Suggested F.Cu target | Notes |
|---|---|---|---|
| `J9` GND | (131.5, 67.0) | `J8` OUTN (117.5, 73.5) | Clear diagonal path; watch `S1_SIG` trace near (136.58, 67.0) |
| `J10` GND | (131.5, 75.0) | `J8` OUTN (117.5, 73.5) | Shortest, mostly clear; watch `S2_SIG` trace running through ~(113–136, 80) |
| `J11` GND | (146.5, 75.0) | `J8` OUTN or `J10` GND | Longer path; route around `S2_SIG`/`S3_SIG` |
| `J12` GND | (146.46, 69.5) | `J8` OUTN or `J9` GND | Longer path; route around `S1_SIG`/`S4_SIG` |

Recommended trace width: at least 0.4mm (existing `B.Cu` ground stitch
near `J8` is only 0.2mm — go wider here given this net's whole failure mode
was "too little margin"). After routing, re-run
`kicad-cli pcb drc --severity-all --schematic-parity` (expect 0 violations)
**and** re-verify with the same "probe outward from the pad, confirm real
zone copper within 1–2mm" check used to find this bug in the first place —
a clean DRC alone already proved insufficient once.

## Consequences

- The two currently-fabricated boards (both from the original OSH Park
  order) carry this defect and need the hand-wired ground jumpers to
  keep functioning. Any other unpopulated board from that same order will
  have the same defect and needs the same jumpers until replaced.
- Boards fabricated from the `.kicad_pcb` file as of 2026-09-20 onward
  include the permanent fix (v2.0.1) — no jumpers needed on new boards
  built from this revision or later.
- This is now a documented, general lesson for this board's layout style
  (heavy reliance on zone-fill-to-pad connections at tight clearances):
  DRC's unconnected-item check is not sufficient proof of a real physical
  connection when a "Solid" zone-connection override is involved. A wider
  point-probe check (as used here) or a visual copper-fill review is
  needed to trust a tight-clearance zone connection before fabrication.
