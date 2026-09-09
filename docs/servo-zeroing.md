# Servo Zero Test

Procedure for flashing firmware and validating steering servo centering
before the horns are mechanically coupled to the wheel/steering linkage.
Written during first bring-up (2026-08-20), when all 4 servos and both
UBECs (U1/U2) were wired but motors were not yet connected.

## Before you start

- Battery voltage: anything above ~9V (3.0V/cell on a 3S pack) is safe to
  bench-test with. A partial charge (e.g. ~11.3V / 3.77V per cell) is fine —
  full charge isn't required for this test.
- It's safe to have all 4 servos connected and powered together for this
  test **as long as the horns aren't yet attached to the wheel/steering
  linkage** — with nothing to bind against, there's no mechanical stall
  risk. Watch and listen on first power-up regardless: a servo that buzzes
  or chatters continuously (rather than moving once and stopping) means
  something's wrong — cut power at the switch immediately if that happens.
- Motor signal lines don't need to be connected yet — `setMotor()`/
  `setSpin()` in the firmware just drive unconnected pins harmlessly if the
  motor driver signal wires aren't wired up.

## 1. Flash the firmware over USB — main battery still disconnected

You need the Arduino IDE (free, from arduino.cc):

1. Install **Arduino IDE 2.x** if you don't have it.
2. Add ESP32 board support: `File → Preferences → Additional boards
   manager URLs` → paste
   `https://espressif.github.io/arduino-esp32/package_esp32_index.json` →
   OK. Then `Tools → Board → Boards Manager`, search "esp32", install the
   Espressif package.
3. Connect the ESP32-S3 dev board via USB (see port note below) — the IDE
   needs the board attached before `Manage Libraries` will let you install
   board-specific libraries.
4. Install the two libraries the firmware needs: `Tools → Manage
   Libraries` → search and install **AlfredoCRSF** and **Adafruit
   NeoPixel**.
5. `Tools → Board` → select your board (closest match to "ESP32S3 Dev
   Module").
6. `Tools → Port` → select the COM port that appeared when you plugged it
   in.
7. `File → Open` → `pathfinder/firmware-elrs/firmware-elrs.ino`.
8. Click **Upload** (→ icon).

### USB port note

Most ESP32-S3 dev boards have **two** USB-C ports, and it matters which one
you use:

- **UART/COM port** — goes through a USB-to-serial bridge chip. Use this
  one for flashing. It shows up as a reliable COM port immediately, and the
  IDE can auto-reset the board into bootloader mode for you.
  **On this board, it's the port on the right side.**
- **Native USB port** — wired directly to the ESP32-S3's own USB
  peripheral. Can also flash, but only enumerates once the chip is running
  in the right USB mode — first-time flashing over it is pickier (may need
  holding **BOOT** + tapping **RESET** to force download mode).

A standard USB-A-to-USB-C cable is fine for the UART port — it only needs
power + the two USB data lines, unlike USB-C PD/Thunderbolt cables that
negotiate extra modes over the CC pins. The one thing to avoid is a
"charge-only" USB-C cable (no data lines) — if the COM port never shows up
in `Tools → Port`, that's the first thing to check.

## 2. Sanity-check over USB alone, before touching the battery

Open `Tools → Serial Monitor` (115200 baud). You should see `Starting
receiver...` then repeating `Waiting for transmitter connection...`. This
confirms the firmware is running and the RGB LED should go white briefly at
boot, then red (waiting for link). Servos won't move yet — USB alone only
powers the ESP32 logic, not the servo rail.

## 3. Power up the servo rail and check centering

Disconnect USB, then connect the main battery. On boot, the firmware calls
`setSteering(0)` once before it starts waiting for the transmitter, so all
4 servos should snap once to their commanded center (90°) and hold there.
That snap-and-hold **is** the zero check — look at each horn and see
whether it lands at true mechanical center.

If a horn is off, correct it now by repositioning the horn on the spline —
since it isn't coupled to the steering linkage yet, this is the right time
to fix gross misalignment mechanically. The firmware `TRIM_*` values (in
`pathfinder/firmware-elrs/firmware-elrs.ino`) are for small on-vehicle
fine-tuning after assembly, not for compensating a grossly misaligned horn.

*(If you want the Serial Monitor open during this step too, you can try
leaving USB connected while adding battery power — most genuine ESP32-S3
DevKit boards arbitrate the two power sources safely, but this isn't
confirmed for this specific clone board. If unsure, stick to USB-only for
step 2 and battery-only for this step.)*

## 4. Optional — exercise full range with the transmitter

To verify direction and travel (not just center), bind the LiteRadio 2 SE
to the RP3-V2 using the traditional button-bind method in
[`docs/elrs-wiring.md`](elrs-wiring.md#method-2-traditional-button-bind)
(quickest, no reflashing the receiver), then move the steering stick and
watch each servo move the right direction without slamming into a hard
stop.

## 5. Iterate trims if needed

If centering looks slightly off, disconnect the battery, adjust
`TRIM_LF`/`TRIM_RF`/`TRIM_LB`/`TRIM_RB` in the `.ino`, reflash over USB
(steps 1 and 3), and repeat step 3. Once satisfied, this closes out the
servo-re-trim item in the Phase 1 checklist — safe to move on to motor and
motor-controller wiring.
