# ADR 0001: Trim ESP32 header pins at GPIO15/GPIO40 instead of a board respin

## Status

Accepted — 2026-09-09

## Context

While re-inspecting the received PCB, a copper pour boundary was found to
pass close enough between two adjacent header pin positions — **GPIO15**
and **GPIO40** on the ESP32-S3 module — that an accidental electrical
bridge across that position is plausible (solder wicking, pin misalignment,
debris). Neither GPIO15 nor GPIO40 is used by the firmware
([`firmware-elrs.ino`](../../pathfinder/firmware-elrs/firmware-elrs.ino)
uses only GPIO 7, 10, 11, 12, 13, 21, 38, 41, 42, 47), so there's no
functional loss in permanently removing them — the only question was how
far to go in response.

Two options were weighed:

1. **Targeted fix** — desolder/remove the ESP32 module's header pins at just
   the two borderline positions (GPIO15, GPIO40), and clip the matching
   socket header pins on the board so no mating contact is even possible at
   that position.
2. **Minimum-viable footprint** — remove *every* ESP32 header pin not
   actively used by the design, leaving only the ~12 pins actually needed
   (signal, power, ground), to eliminate any possibility of stray-voltage
   interaction with an unused GPIO anywhere on the board, not just at the
   one known trouble spot.

### Pin audit performed for Option 2

Cross-checked the proposed keep-list against
[`firmware-elrs.ino`](../../pathfinder/firmware-elrs/firmware-elrs.ino) and
[`papaya-wiring-layout.yaml`](../../papaya-wiring-layout.yaml):

- All 10 firmware-used GPIOs (7, 10, 11, 12, 13, 21, 38, 41, 42, 47) were
  correctly identified in the proposed keep-list. Nothing functional was
  missing.
- GPIO48 (onboard RGB status LED) does **not** need to be kept — it's wired
  internally on the ESP32-S3 module itself and never appears in the wiring
  YAML's ESP32 connection points, so it isn't routed through the header
  into the custom PCB at all.
- The wiring model defines two separate ESP32 ground connection points,
  `GND_1` ("near 5V IN") and `GND_2` ("near TX"), both landing on the same
  board ground pour. Initial concern that `GND_2` might refer to the
  ELRS-mapped GPIO21 (`TX_PIN` in firmware) was incorrect — the "TX" in
  `GND_2`'s label refers to the ESP32 module's own silkscreen-labeled `TX`
  pin (right header pin #2, the default UART0 pin), not GPIO21/47 which
  carry ELRS CRSF traffic over HardwareSerial2. Moot either way: the
  ESP32 module ties all its own GND pins together internally, so a single
  intact ground path is electrically sufficient regardless of which
  physical GND pin is used.
- EN (reset) and IO0 (boot strap) pins are not needed on the header:
  programming and auto-reset go through the module's own USB port via a
  self-contained circuit on the ESP32-S3 board, independent of the header
  into the custom PCB.

So Option 2 was electrically sound and slightly over-provisioned (more
ground pins than strictly required), but it was rejected anyway.

## Decision

**Go with Option 1** — trim only the GPIO15/GPIO40 pins (module side and
matching board socket pins), leaving all other unused header pins intact.

## Rationale

- Option 2 would remove roughly 32 of 44 header pins, leaving the module
  mechanically retained in its socket header at only ~12 friction points.
  On a full-size rover that will see real vibration and shock loading in
  use, that's a meaningful reduction in mechanical retention — a concern
  independent of and not solved by the electrical benefit.
- The actual, observed failure mode (pour proximity) is localized to one
  pin pair. The rest of the unused pins aren't near any pour boundary and
  aren't at realistic risk — Option 2 would have spent extra rework
  eliminating a mostly hypothetical risk elsewhere on the board.
- Option 1 avoids soldering up a third board revision while directly
  closing off the one known short path.

## Consequences

- GPIO15 and GPIO40 become permanently unusable on this board without a
  respin — acceptable since neither is used by the firmware today or
  planned for Phase 2 (LIDAR/autonomy) at time of writing.
- If a future pin budget crunch (e.g. Phase 2 sensor expansion) needs
  GPIO15 or GPIO40 specifically, this board will need a physical rework or
  a respin at that time — revisit this ADR if that happens.
- The broader "unused pin stray-voltage" risk Option 2 would have
  addressed remains theoretically present elsewhere on the board, unless a
  future respin closes it at the layout level (e.g. wider pour clearance
  from all header pad positions).
