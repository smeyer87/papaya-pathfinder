# Build Guide — From Scratch

A step-by-step path from "empty parts bin" to "driving under ELRS control,"
written after finishing Phase 1 of this build. Every step here exists
because something in that process either went wrong the first time or was
worth getting right before power was ever applied — see
[`docs/development-log.md`](development-log.md#phase-1-bring-up-2026-08-20--2026-09-19)
for the full narrative if you want the "why," and the
[Common pitfalls](#common-pitfalls-quick-reference) table at the end for a
condensed version.

This guide sequences and cross-links the existing detailed docs rather than
duplicating them — follow it in order, and follow the links when a step
says to.

## 1. Buy the parts

**On-board components** (things that mount directly to the custom PCB):
see [`pathfinder/BOM.md`](../pathfinder/BOM.md) for the exact parts
purchased, Amazon ASINs, and measured footprints — ESP32-S3 dev board,
both UBECs, screw terminals, header pins.

**Off-board system components**, not covered by the BOM (footprints for
these aren't on the PCB — they connect via the header/terminal
connectors the BOM does cover):

| Part | Model used in this build | Notes |
|---|---|---|
| Motor drivers | 2× BTS7960/IBT_2 | One per side |
| Drive motors | 6× GA25 DC gear motors | 3 ganged per side, one PWM signal per side |
| Steering servos | 4× Miuzei DS3218 (metal gear) | Rated 6–7.4V — matches the 6V servo bus by design |
| RC receiver | RadioMaster ELRS-RP3-V2 | 2.4GHz ELRS V3 |
| RC transmitter | BETAFPV LiteRadio 2 SE | 2.4GHz ELRS V3, Mode 2 |
| Battery | 3S LiPo | Feeds both UBECs directly |

If you substitute a different servo model, **check its rated voltage
before connecting it** — don't assume 6V is universally safe. Micro
servos (SG90/MG90S-class) are commonly rated only 4.8–6V, right at or
past the top of that range; metal-gear servos like the DS3218 above are
usually fine into the 6–7.4V range. When a servo has no printed spec,
look up the exact model/part number rather than guessing.

## 2. Get the PCB fabricated

The board is designed YAML-first —
[`papaya-wiring-layout.yaml`](../papaya-wiring-layout.yaml) is the system
source of truth, and the KiCad project at
[`pathfinder/kicad/papaya-pcb/`](../pathfinder/kicad/papaya-pcb/) is
generated/laid out from it. See
[`docs/development-log.md`](development-log.md) for the full design
narrative if you're starting a layout from scratch.

As of v2.0.1, the committed `.kicad_pcb` file already includes the
permanent servo-ground fix from [ADR 0002](adr/0002-servo-header-ground-isolation.md)
— boards fabricated from the current file don't need the hand-wired
jumper workaround in step 4 below. If you're working from an older copy
of the file (pre-2026-09-20), apply that fix first and re-verify with
`kicad-cli pcb drc --severity-all --schematic-parity` (expect 0
violations) **and** a visual copper-fill review in the KiCad GUI — a
clean DRC run alone was not sufficient to catch this defect the first
time.

OSH Park (or an equivalent fab) accepts the `.kicad_pcb` file directly, or
use the Gerbers already exported to
[`pathfinder/kicad/papaya-pcb/gerbers/`](../pathfinder/kicad/papaya-pcb/gerbers/)
(regenerate these if you change the design — `kicad-cli pcb export
gerbers` / `pcb export drill`).

## 3. Trim the ESP32 header pins

Before seating the ESP32-S3 module in its header, remove its GPIO15 and
GPIO40 pins (desolder/clip both the module's own pins and, if not already
excluded, the matching board socket pins). Neither pin is used by the
firmware. See [ADR 0001](adr/0001-esp32-header-pin-trimming.md) for why —
a copper pour boundary on this board passes close enough between those two
positions to risk an accidental short. The rest of the module's unused
header pins are left in place for mechanical retention.

## 4. Wire everything up

Wire per [`papaya-wiring-layout.yaml`](../papaya-wiring-layout.yaml) and
the pin tables in [`docs/elrs-wiring.md`](elrs-wiring.md). A few points
that caused real problems in this build, worth doing deliberately rather
than quickly:

- **Motor power distribution terminal block:** wire this carefully against
  the wiring diagram and double-check polarity and terminal positions
  before ever applying power. A miswired distribution block here shorted
  the motor supply during this build's first full bring-up — it looked
  like a dead motor driver, not a wiring mistake, until traced back.
- **Servo connectors:** match pins by **position**, not by wire color —
  color conventions vary between servo brands (e.g. brown vs. black for
  ground on different manufacturers). The reliable anchor is that power
  (red) is always the center pin of the 3-pin connector; ground and signal
  are the two outer pins, whichever colors your specific servo uses.
- **Servo ground jumpers (temporary, until a fixed board is fabricated):**
  if you're building on a board fabricated before ADR 0002's permanent fix
  is applied, run one wire per servo connector from `J8`'s ground terminal
  directly to that connector's `GND` pin — soldered, not just clipped on,
  and one wire per connector rather than daisy-chained. Without this, all
  four servos will be completely unresponsive despite everything else
  working correctly. See [ADR 0002](adr/0002-servo-header-ground-isolation.md)
  for why.
- **Tight-pitch connectors and multimeter probes:** the servo headers are
  on a 2.54mm pitch. Prefer soldered or alligator-clipped test leads over
  hand-held pointed probes when checking voltages there — a probe slip
  bridging two adjacent pins destroyed a board during this build's
  diagnosis.

## 5. Flash the firmware

Follow [`docs/servo-zeroing.md`](servo-zeroing.md) section 1 for the full
Arduino IDE setup (board support, required libraries, board/port
settings) and the USB port note (use the UART port, not the native-USB
port, for flashing — on this hardware it's the port on the right side).

## 6. Bring-up and test, in this order

Go cold-to-hot, verifying each layer before powering the next, rather than
connecting everything and flipping the switch:

1. **Dry checks, no power, ESP32 not yet seated (or removed).** With a
   multimeter in resistance mode: confirm no continuity between the
   GPIO15/GPIO40 pad positions and neighboring copper (validates step 3).
   Confirm continuity from `J8`'s ground terminal to each servo `GND` pin
   reads near 0Ω (validates step 4's ground jumpers, or the permanent fix
   if your board has it) — this single check would have caught the ground
   isolation defect before any firmware was even involved.
2. **USB only, battery disconnected.** Flash the firmware, open Serial
   Monitor (115200 baud), confirm clean boot output (`Starting
   receiver...` then repeating `Waiting for transmitter connection...`),
   RGB LED white then red. This is a pure logic-side smoke test.
3. **Battery only, USB disconnected.** Check `U1` (6V) and `U2` (5V)
   output voltage — and just as importantly, check voltage **at the
   actual servo/motor connectors**, not only at the UBEC's own output
   terminal. A rail can measure perfectly clean at its source while never
   reaching the load if something's broken downstream (exactly what
   happened with the ground isolation defect). All four servos should
   snap once to center on boot and hold — that's the servo-zero check;
   see [`docs/servo-zeroing.md`](servo-zeroing.md) section 3 for details
   and what a buzzing/chattering servo means (cut power immediately).
4. **Bind the transmitter and receiver.** Follow
   [`docs/elrs-wiring.md`](elrs-wiring.md#method-2-traditional-button-bind)
   (button-bind method). If binding doesn't complete and the receiver has
   ever been flashed with a custom binding phrase before, it won't
   re-enter bind mode until that phrase is explicitly cleared first — see
   the callout in that doc.
5. **Full-range control test.** Cycle both sticks through their full range
   (individually and together) and cycle every switch through every
   permutation, watching steering, throttle, and spin-in-place respond
   correctly with no unexpected behavior at any input combination.

If something doesn't respond, check power **at the connector actually
driving the silent component** before suspecting firmware — in this
build, both major failures (a shorted motor supply, and four isolated
servo grounds) looked identical to a code problem until traced with a
multimeter.

## Common pitfalls quick-reference

| Symptom | Cause | Where it's covered |
|---|---|---|
| Board won't flash / boot-loops after a COM dropout | Corrupted flash partition or genuine hardware fault (spare-board swap is the fastest diagnostic) | [`docs/development-log.md`](development-log.md#first-power-on-and-an-esp32-hardware-fault) |
| Possible short between two specific header pin positions | Copper pour proximity — GPIO15/GPIO40 | [ADR 0001](adr/0001-esp32-header-pin-trimming.md) |
| Receiver won't enter bind mode | A binding phrase was set previously and was never cleared | [`docs/elrs-wiring.md`](elrs-wiring.md) |
| No servo/motor movement despite clean rail voltage at the UBEC | Rail measured at the source, not the load connector — check downstream | [`docs/development-log.md`](development-log.md#full-system-retest-surfaces-two-real-unrelated-defects) |
| All four servos silent, motors fine | Servo header GND pads isolated from ground pour | [ADR 0002](adr/0002-servo-header-ground-isolation.md) |
| One motor channel dead, other fine, same firmware | Check the motor driver's enable pins and the power distribution terminal block wiring before suspecting the driver itself | [`docs/development-log.md`](development-log.md#full-system-retest-surfaces-two-real-unrelated-defects) |
| Board damaged while probing with a multimeter | Bare pointed probes bridging adjacent pins on a tight-pitch header | This guide, step 4 |
