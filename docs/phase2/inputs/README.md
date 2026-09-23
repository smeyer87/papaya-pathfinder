# Phase 2 Planning Inputs

Raw-but-organized planning notes that feed the Phase 2 design session.
These are **inputs**, not a design — nothing here is final until it lands
in a spec under `docs/superpowers/specs/` or an ADR under `docs/adr/`.

Baseline for everything here is the Phase 1 build as documented in
[`../../superpowers/specs/2026-08-16-phase1-current-state.md`](../../superpowers/specs/2026-08-16-phase1-current-state.md)
— don't re-describe Phase 1 hardware in these files, just reference it.

## Files

| # | File | Answers | ID prefix |
|---|---|---|---|
| 0 | [`00-inbox.md`](00-inbox.md) | "I don't know where this goes yet" | — |
| 1 | [`01-missions.md`](01-missions.md) | What should the rover *do*, where, and what's out of scope? | `MP-` |
| 2 | [`02-capabilities.md`](02-capabilities.md) | What logical abilities do those missions require? | `CAP-` |
| 3 | [`03-sensors-compute-electronics.md`](03-sensors-compute-electronics.md) | What sensors, compute, power, and comms hardware supports them? | `SEN-` / `CMP-` / `PWR-` / `COM-` |
| 4 | [`04-physical-platform.md`](04-physical-platform.md) | What mechanical/chassis changes does all of the above need? | `PLT-` |
| 5 | [`05-assumptions-decisions.md`](05-assumptions-decisions.md) | Constraints, assumptions, decisions made, open questions | `CON-` / `A-` / `D-` / `Q-` |

## How to fill these in

- **Don't over-sort.** If a note doesn't obviously belong somewhere, drop
  it in `00-inbox.md`. Each file also has a `Raw notes` section at the
  bottom for anything half-formed.
- **Give items IDs** (`MP-1`, `CAP-4`, …) and reference upstream IDs in a
  `Supports:` line. This is how we keep the files linked without merging
  them. IDs are permanent — if you drop an item, mark it `~~struck~~`
  rather than renumbering.
- **Top-down is ideal, bottom-up is fine.** If a note starts from a
  technology ("I want to try LIDAR"), write it where it belongs and set
  `Supports:` to the mission it enables — or to a learning goal
  (`MP-L1`, etc.) if the real reason is "I want to learn this."
- **Priority** on every mission and capability: `Must` / `Should` /
  `Could`. This is what lets an ambitious list get phased.
- **Uncertainty is valuable.** "Not sure if X or Y" goes straight into
  `05` as an open question (`Q-`) — those become the design session agenda.

## Flow

```
01 Missions ──► 02 Capabilities ──► 03 Sensors/Compute ──► 04 Platform
      │                │                     │                  │
      └────────────────┴──────────┬──────────┴──────────────────┘
                                  ▼
                   05 Constraints / Assumptions /
                      Decisions / Open Questions
```
