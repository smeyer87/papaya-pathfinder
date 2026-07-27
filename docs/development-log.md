# Development Log

Summary of the electronics/wiring/schematic work done on this fork so far.
Written as a project memory anchor — background and reasoning, not just a
changelog.

## Background

This fork builds the full-size **Pathfinder** (not `pathfinder-mini`). The
electronics were originally hand-wired onto a pre-drilled prototyping board
per the upstream project's Fritzing diagrams
(`pathfinder/schematics/*.png`), plus a hand-added ELRS receiver
(RadioMaster RP3-V2) the upstream project didn't document. That manual
soldering process didn't go well, so the plan shifted to designing a proper
custom PCB in KiCad instead.

## 1. System wiring model — `papaya-wiring-layout.yaml`

Rather than jumping straight into KiCad, we first built a YAML model of the
**entire electrical system** — not just the PCB, but every off-board part
and how it all connects — as a source of truth that could later drive the
schematic. Iteratively developed into:

- **`components`**, each with a `componentType` (`battery`, `fuse`,
  `switch`, `terminalBlock`, `offBoard`, `board`) and a list of
  `connectionPoints` (the specific pins/terminals/pads that can be wired).
- **`connections`**, each a `from`/`to` pair of `{component, point}` plus a
  `medium` (`wire`: color/gauge/length, or `trace`: PCB copper layer/width).
- **`bondedGroups`** on a component — points permanently tied to one
  electrical net via a physical jumper bar (terminal block ganging) or an
  on-board copper bus (power/ground planes), so you don't have to write out
  a chain of pairwise jumper connections.
- A `connector` type (`screwTerminal` / `solderPad` / `pinHeader` /
  `socketHeader`) on board-side connection points, for later footprint
  assignment.

**Full system modeled:** LiPo 3S battery → fuse → switch → a power
distribution terminal block (`tb-power-dist`, real terminal numbers per the
physical device, not sequential) feeding four branches — two BTS7960 motor
drivers (`BTS1`/`BTS2`), a UBEC 5V/3A (`u2`, solder-mounted on the board)
and a UBEC 6V/8A (`U1`, off-board) — an ESP32-S3, an ELRS receiver
(RadioMaster RP3-V2), 6 drive motors ganged in two banks of 3 via a marine
terminal bus (`tb-motor-bus`) with real hardwire-jumper ganging, and 4
steering servos. On-board 5V/6V/ground buses modeled as `bondedGroups` on
the board itself; the full ground loop was traced end-to-end back to the
battery negative terminal and verified closed.

**Real data captured:** actual wire gauges (14 AWG main feed, 18 AWG
distribution-block branches and motor-driver supply, 20 AWG motor legs,
22 AWG signal/servo/ELRS wiring), and the terminal block's real
manufacturer-printed numbering (not sequential — verified against the
physical device).

**Caught along the way** (worth remembering — these were real mistakes,
not just style nits):
- A servo GPIO-to-position mapping I'd invented early on turned out to
  contradict the user's own `docs/build-notes.md` (their authoritative
  from-the-bench wiring record) — corrected to match the build notes, not
  the upstream Fritzing diagram.
- An early placeholder connection (switch feeding the motor bus directly)
  became wrong once the BTS drivers were modeled — the real power path is
  switch → distribution → driver output → motor bus. Caught and fixed.
- `tb-power-dist`'s "master input bonded to every terminal" was described
  in a note but never actually encoded as a `bondedGroups` entry — added,
  which is what let the ground-loop check actually verify closure.
- Wire gauge fields still carried my original placeholder value
  (`"14 AWG" # e.g. "14 AWG"`) on the main battery feed — flagged before
  the user supplied real numbers, rather than letting placeholder data look
  authoritative.

**Final state:** 22 components, 88 connections, validated with a
referential-integrity script (every connection/bondedGroup point resolves
to a real connectionPoint, no orphaned points, no duplicate ids).

## 2. KiCad schematic generator — `pathfinder/kicad/scripts/generate_schematic.py`

A script that reads the wiring YAML and writes a fully-wired starter
`.kicad_sch` for the empty `pathfinder/kicad/papaya-pcb/` project, so KiCad
work starts from "everything's already wired" instead of a blank sheet.

- Computes electrical nets via union-find over every `connections` entry
  and every `bondedGroups` list.
- Every non-`board` YAML component becomes one schematic symbol (generic
  labeled box, one pin per `connectionPoint`, generated and embedded
  directly in the file — no external library dependency) and is flagged
  `on_board no` ("Exclude from Board"), since it isn't part of the PCB.
- `board-main`'s `connectionPoints` are grouped by id prefix (e.g.
  `J_ESP32.7`, `J_ESP32.12`, ... → one `J_ESP32` connector) into real
  on-board connector symbols (`on_board yes`).
- Every net becomes a local label at each member pin (stub wire + label),
  rather than computed point-to-point routing between arbitrarily-placed
  symbols.
- Reference designators are rule-based (ids already shaped like a
  designator, e.g. `BTS1`/`M3`, are reused as-is; otherwise a
  `componentType`-based prefix + counter), so it keeps working as more
  components are added to the YAML later without script changes.

**Validated, not just written and trusted:** the exact `.kicad_sch`
S-expression syntax was extracted from the real KiCad 10.0 install on this
machine (bundled symbol libraries and demo projects), not written from
memory — the schema version in this project's stub (`20260306`) postdates
general training knowledge, so guessing from memory demonstrably produced
invalid files on the first few tries. Final output was checked with
`kicad-cli sch erc`: **0 errors** across the full generated schematic (33
symbols, 20 nets), plus an independent script cross-checking the symbol/net/
pin counts against the source YAML.

## 3. GitHub fork setup

Confirmed `origin` = this fork (`smeyer87/papaya-pathfinder`, push target)
vs. `upstream` = the original project (`tronxi/papaya-pathfinder`,
read-only, no write access). A plain `git push`/sync only ever touches the
fork — nothing reaches the upstream project unless a PR is explicitly
opened later, which is a separate deliberate step.

## Next steps

- Open the generated schematic in KiCad, rearrange the auto-placed grid
  layout, assign real footprints to the 12 on-board connectors, and run
  "Update PCB from Schematic" to get a ratsnest to lay out.
- Model the servo power bus / UBEC 6V connections' PCB traces once footprint
  choices are made (currently modeled electrically in the YAML, not yet
  laid out).
