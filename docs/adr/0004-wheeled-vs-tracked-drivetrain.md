# ADR 0004: Keep wheeled rocker-bogie drivetrain; reject tracked and other alternative architectures

## Status

Accepted — 2026-10-02

## Context

Phase 2 sensor/compute additions are forcing a substantial payload-bay
redesign (`docs/phase2/inputs/04-physical-platform.md` PLT-5), and a
wheel/axle redesign is already underway for two independent reasons: a
recurring printed steering-pivot-pin failure (PLT-7) and a longer
wheelbase needed to match the larger bay (Q-9, 6-vs-8-wheel). With this
much of the drivetrain already open for rework, it's a natural point to
ask whether the overall drivetrain *architecture* — not just the wheel
suspension — is still the right choice, rather than patching the current
approach without reconsidering it.

Four architectures were weighed:

1. **Tracked / caterpillar drivetrain.** Pros: better flotation/traction
   on soft or very uneven ground; steering is typically skid-steer only,
   no steering-knuckle complexity at all. Cons: track tensioners, drive
   sprockets, and track wear/replacement add significant mechanical
   complexity, weight, and cost versus wheels; track maintenance is a
   real recurring burden, not a one-time cost.
2. **Mecanum / omni wheels.** Pros: lateral/strafing movement, tight
   maneuvering in confined spaces. Cons: the small rollers that give
   omni wheels their lateral capability are known to perform poorly
   outdoors on anything but smooth, hard, flat surfaces — grass, dirt,
   and mild unevenness tend to defeat them. Wrong tool for this terrain.
3. **Fully independent coil-over suspension per wheel** (abandon the
   rocker-bogie's passive, geometry-based articulation entirely). Pros:
   simpler single-wheel kinematics; removes the transverse-differential/
   chassis-torsion coupling question entirely (see Q-11 — there'd be
   nothing to couple). Cons: loses the rocker-bogie's ability to span
   step-like obstacles via arm leverage rather than relying purely on
   spring compression; would require re-engineering every wheel mount,
   not just the one joint that's actually failing — discarding the
   "pivot"/"bogey" structural mounts that have never been a problem.
4. **Legged/walking locomotion** (e.g. a Theo Jansen-style linkage).
   Rejected quickly: a large jump in mechanical and control complexity
   with no capability benefit for a mostly-flat terrain profile.

## Decision

**Keep the existing wheeled rocker-bogie drivetrain** (6-wheel today,
likely 8-wheel per Q-9), and retrofit a knuckle-and-shock suspension at
the specific joint that's actually failing (PLT-7) rather than replacing
the drivetrain architecture.

## Rationale

- `A-2` (mild, mostly-flat farm terrain; major hazards geofenced out;
  human-walking-pace operation) doesn't demand tracked-vehicle-grade
  traction or flotation — that capability would solve a problem this
  rover doesn't have.
- The rocker-bogie's structural mounts (the "pivot"/"bogey" parts) have
  never been among the observed failure modes — reusing them, rather
  than replacing the whole architecture, avoids re-solving an
  already-solved problem.
- Tracks, mecanum, and legged locomotion all add substantial cost,
  weight, and complexity with no capability gain for this specific
  mission profile.
- None of the alternatives fix the actual observed failure anyway: the
  printed steering-pivot-pin problem (PLT-7) is a strut/joint design
  issue, not a drivetrain-architecture issue — a tracked vehicle still
  needs a mechanism translating motor rotation into motion and still
  needs shock absorption for ride quality over washboard; changing
  architecture wouldn't make the print-strength problem disappear.

## Consequences

- Keeps the existing motor/servo/driver investment valid and reusable
  (6× GA25 motors, 4× DS3218 servos, 2× BTS7960 drivers) rather than
  stranding it on an architecture change.
- Revisit if `A-2`'s terrain assumption changes — e.g. a future mission
  requires crossing genuinely soft or rough terrain wheels can't handle.
  Considered unlikely given the stated farm-terrain mission profile, but
  not foreclosed.
