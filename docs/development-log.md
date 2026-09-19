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

## 4. PCB layout, routing, and fabrication

With the schematic generated and ERC-clean, the remaining work was turning
it into an actual board: real footprints, a physical layout, copper pours,
routed traces, mounting provisions, and finally Gerbers to send to a fab
house. Unlike the schematic (script-generated), this phase was done by hand
in the KiCad GUI — the user's first time using KiCad — with `kicad-cli`
DRC runs as the authoritative check after every change, rather than relying
on visual inspection of the canvas.

### Footprint assignment

Real footprints were assigned to all 12 board connectors based on parts the
user actually purchased (documented with Amazon ASINs and physical
measurements in `pathfinder/BOM.md`), not generic library defaults. Where no
standard library footprint matched both the physical part *and* the
schematic's real pin names, a custom footprint was built in the project's
own `papaya-pcb.pretty` library:

- `ESP32S3_DevKit_2x1x22_split` — the dev board is two separate 1x22 header
  rows, not one 2x22 block. Row spacing/pad/drill were deliberately
  loosened (2.54mm pitch, 25.40mm row spacing, 1.1mm drill, 2.0mm pad) from
  the raw measured 25.5–26.0mm spacing, trading a little precision for
  assembly tolerance.
- `PinHeader_1x06_BTS_Signal`, `PinHeader_1x04_ELRS`, `PinHeader_1x03_Servo`,
  `TerminalBlock_2Pos_UBEC6V`, `UBEC_5V_3A_10x15mm` — pad-renamed copies of
  standard parts, needed because the standard library's default sequential
  pad numbering (`1`, `2`, `3`...) didn't match the schematic's named pins
  (e.g. BTS driver signal pins skip 5/6; ELRS/servo pins are named, not
  numbered).

**Caught along the way:** newly-created custom footprints weren't picked up
by "Update PCB from Schematic" until KiCad was fully closed and reopened —
the running session had already scanned the library folder before the files
existed. Same root cause recurred with the Footprint Editor showing stale
pad positions. And the ESP32 footprint's first build had the two header
rows mirrored (as if viewed from the bottom) — caught by the user physically
comparing the dev board against the KiCad 3D/2D view, not by DRC (mirroring
doesn't produce a DRC error, since it's still internally consistent).

### Layer strategy and copper pours

Two-layer board, 70×90mm outline. B.Cu was reserved entirely for
power/ground copper pours (`5V_POUR`, `6V_POUR`, `MASTER_GND`); F.Cu was
reserved for all component placement and signal routing. This split meant
signal traces never had to "thread through" a pour on the same layer — a
simpler mental model for a first KiCad project than mixing pours and traces
on one layer.

Where the 5V/6V/ground pours overlap in area, KiCad's zone *priority*
setting decides which one wins that territory. This needed real iteration:

- Default 0.5mm pad-to-zone clearance was too wide for the servo headers'
  2.54mm pitch (GND/PWR/SIG) — pads failed to connect to their pour.
  Lowered to 0.2mm clearance on the affected zones, which resolved it
  without manual routing.
- Adding the ground pour after the power pours were already tuned inverted
  the intended priority order, causing ground to silently swallow part of
  the 6V pour's territory and regress a previously-working net. Fixed by
  re-ordering zone priority (ground lowest, then 5V/6V above it).
- A handful of pads adjacent to a higher-priority pour had too little room
  for a standard 4-spoke thermal relief ("starved thermal," spoke count 1
  of 2 required). Fixed per-pad via the "Pad connection to zones" override
  set to Solid.
- A few pads were genuinely too deep inside a higher-priority zone's
  rectangle for either of the above to help (no nearby edge of their own
  net's copper to reach). These got a short manual "escape stub" trace
  routed from the pad out to open same-net territory, then zones were
  refilled.

### Verification discipline

Every layout change was checked with `kicad-cli pcb drc --severity-all
--schematic-parity`, and major milestones got a full net-by-net comparison
between the PCB's actual netlist and the nets computed from the YAML
(`build_nets()` in the generator script) — not eyeballing ratsnest lines.
This caught real problems, but also two lessons about *how* to verify:

- A rotation-math bug of my own — I computed which pad (`INN` vs `OUTN`) on
  a -90°-rotated footprint was trapped inside a pour using a hand-rolled
  rotation matrix with the wrong sign convention, and gave the user
  incorrect instructions as a result. The user caught it by checking their
  own visual against the coordinates DRC itself reported. Lesson applied
  for the rest of the project (and reused for the mounting-hole work
  below): trust DRC's own reported coordinates for anything involving
  rotated footprints, never hand-rolled rotation math.
- A false alarm in the other direction — I raised concern about "5
  disconnected islands" based on counting separate polygon entries in a
  zone's fill data, which DRC did not actually flag as a problem. The
  polygon count was a red herring (thermal-relief spokes render as separate
  polygon entries even when electrically fine); corrected once DRC's own
  output was checked directly.

Before committing to fabrication, the user physically validated the design
outside of KiCad entirely: a 1:1-scale paper printout of the board with the
real purchased components laid on top, confirming footprint sizing and
placement matched the physical parts.

### Mounting holes

Four M3-clearance (3.2mm) NPTH mounting holes were added at the board
corners late in the process, after routing was otherwise complete — a
requirement (mounting to the robot base) that hadn't been captured in the
original YAML model, since it's mechanical rather than electrical.

This surfaced a real layout conflict: two of the four corners (near
connectors `J7` and the servo header cluster `J9`–`J12`) had no clear space
for a true corner-inset hole once the connectors' courtyards were checked
precisely — the top edge of the board was more tightly packed than an
earlier quick visual check had suggested. Rather than shrink the mounting
hardware or accept holes far from the actual corners, the user chose to
manually reposition `J7` and the servo cluster to open up the corners,
re-verified via DRC after each move.

Two things worth remembering from this step:

- **KiCad's bundled Python (`pcbnew` module, at
  `<KiCad install>/bin/python.exe`) can load, edit, refill zones on, and
  save a `.kicad_pcb` file headlessly** — used here to fill zones and to
  query exact world-space footprint/courtyard bounding boxes
  (`fp.GetBoundingBox()`, per-item `GetBoundingBox()` for `F.CrtYd` shapes)
  instead of computing them by hand, avoiding a repeat of the rotation-math
  bug above.
- **A near-miss with data loss**: mounting holes inserted directly into the
  `.kicad_pcb` file were silently dropped after the user's next save,
  because their KiCad GUI window was still open on the *pre-edit* version of
  the board — KiCad wrote its own in-memory model back to disk, overwriting
  the on-disk changes it never loaded. Recovered by diffing against the
  last git commit (the user's actual layout edits were unaffected, only the
  holes were lost) and re-applying. Takeaway: when a script and an open
  KiCad GUI session might both write the same file, close the GUI first.
- A handful of pads near the new top-left hole briefly showed as
  disconnected after refilling zones; tracing it down (including
  temporarily removing the hole and diffing against the last commit) showed
  it was a pre-existing, benign zone-fill artifact — a hairline "keyhole"
  seam in an unused corner of the ground pour with no pad depending on
  it — present before the mounting holes were ever added, not caused by
  them. An attempt to clean it up by raising the zone's minimum copper
  thickness board-wide was reverted after it broke two real, previously
  working connections elsewhere that depended on the tighter clearance;
  left alone rather than risk a working board for a cosmetic DRC line.

### Fabrication

OSH Park was chosen as the fab house — US-based (no customs/tariff
concerns for this build) with an acceptable turnaround, and it accepts a
direct `.kicad_pcb` upload rather than requiring manual Gerber export.
Gerbers (7 layers: F/B copper, F/B silkscreen, F/B mask, edge cuts) plus an
Excellon drill file, drill map, and job file were generated anyway via
`kicad-cli pcb export gerbers` / `pcb export drill` as a fabrication-ready
fallback and a permanent record of exactly what was sent out, committed to
the repo under `pathfinder/kicad/papaya-pcb/gerbers/`.

Final state before the order was placed: 0 DRC violations, full net-by-net
parity against the YAML across every net, mounting holes clear of all
components and copper pours.

## Phase 1 bring-up (2026-08-20 – 2026-09-19)

Boards arrived from OSH Park and assembly/bring-up began. This section
covers the path from first power-on to a fully working drivetrain —
including two real hardware defects found along the way, since both are
now permanent lessons for this board design.

### First power-on and an ESP32 hardware fault

First power-on (2026-08-20) was successful: firmware flashed, both UBECs
(`U1` 6V, `U2` 5V) measured clean, no smoke/damage. Servo motion wasn't
directly observable that session (servos mounted inside a housing).

During later ELRS bring-up (2026-09-01), a COM port dropout during a
reflash corrupted the ESP32's app partition. Recovery attempts (reflash,
slower upload speed, corrected flash size — the module is actually a
`ESP32-S3-WROOM-1-N16R8`, 16MB flash / 8MB octal PSRAM, not the 4MB the
Tools menu was set to — full chip erase, DIO vs QIO flash mode) all
failed identically, including with the stock unmodified `Blink` example,
which ruled out project firmware entirely. Swapping in a spare board from
the same 3-pack confirmed a genuine hardware fault (likely the flash chip)
on the original unit — `Blink` booted clean on the spare immediately. The
module is socketed via Dupont headers rather than soldered direct, which
made the swap trivial. **Lesson:** when a stock example sketch fails
identically to project firmware after eliminating every software variable,
suspect the silicon, not the code.

### GPIO15/GPIO40 pour proximity (ADR 0001)

Re-inspecting the received PCB found a copper pour boundary passing close
enough between the GPIO15 and GPIO40 header pin positions to risk an
accidental bridge (solder wicking, pin misalignment, debris). Neither pin
is used by the firmware, so the fix was to trim just those two header pins
(module side and matching board socket pins) rather than a full respin —
see [`docs/adr/0001-esp32-header-pin-trimming.md`](adr/0001-esp32-header-pin-trimming.md).
A second physical board was assembled with those two pins excluded.

### Full-system retest surfaces two real, unrelated defects

With the GPIO15/40-trimmed board built, motors newly wired in, and a
fresh ESP32 installed, a full retest (2026-09-18/19) initially showed
**zero response from every servo and every motor**, despite the ELRS link
coming up clean and the 6V/5V rails both measuring correct at their UBEC
outputs. Working through this methodically (see the session transcript for
the full diagnostic trail) turned up two independent problems hiding
behind each other:

1. **Motor power distribution terminal block was miswired**, effectively
   shorting the motor supply. Corrected by rewiring the terminal block
   per the intended polarity/positions; motors then responded 100% to
   controller input on the first retest. This was a wiring mistake, not a
   board or firmware defect.
2. **All four servo header GND pads (`J9`–`J12`) were physically isolated
   from the ground pour** — a real PCB layout defect, confirmed by a
   0Ω/∞Ω resistance test and then traced to its root cause in the KiCad
   file itself. Full writeup, including the exact copper geometry and a
   recommended permanent fix, is in
   [`docs/adr/0002-servo-header-ground-isolation.md`](adr/0002-servo-header-ground-isolation.md).
   Short-term fix: hand-soldered ground jumper wires from `J8`'s ground
   terminal to each servo `GND` pin, bypassing the pour. Verified working
   — all four servos now respond correctly to both boot-time centering and
   live transmitter input.

**Lessons carried forward from this session:**

- A clean DRC run and a correctly-set zone-connection override are **not**
  proof that a tight-clearance pad is actually reached by poured copper —
  DRC's unconnected-item check verifies net assignment, not physical
  continuity of the pour body. The only way this was actually caught was
  probing outward from the pad in software and independently with a real
  ohmmeter on the physical board. See ADR 0002 for the full technique.
- When several actuators fail identically (all 4 servos, both motors),
  suspect a shared cause (power/ground) before suspecting N independent
  signal-wiring failures — but verify power *at the actual load
  connector*, not just at the UBEC's own output terminal. Rail voltage
  measured clean at the source can still fail to reach the actual load if
  something's broken downstream.
- Probing tightly-pitched headers (2.54mm servo connectors) with bare
  pointed multimeter probes carries real short risk — one such short
  destroyed a board mid-session. Prefer soldered or clipped test leads
  over hand-held point probes on tight headers.
- Substitution testing with a single known-good component (one spare
  servo, tried in all four positions) cleanly ruled out "bad batch of new
  servos" as a hypothesis in one cheap step, before any deeper board-level
  investigation was warranted.

## Next steps

- Phase 1 build is complete: full drivetrain (4 servos + 2 motor
  channels) confirmed responding correctly to ELRS transmitter input.
  Wheels being attached next; steering trims still need on-vehicle
  fine-tuning once wheels are on.
- Before any board reorder: apply the permanent ground-trace fix in
  [ADR 0002](adr/0002-servo-header-ground-isolation.md) to the `.kicad_pcb`
  file and re-verify — do not resubmit the existing Gerbers as-is.
- Phase 2 (LIDAR/autonomy) not yet scoped — see
  `docs/superpowers/specs/2026-08-16-phase1-current-state.md` and use
  `superpowers:brainstorming` when it kicks off.
