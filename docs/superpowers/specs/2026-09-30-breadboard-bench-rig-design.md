# Breadboard Bench Rig — Design Notes

*Approved 2026-09-30.*

**Motivation:** before committing to a full PCB respin, validate real
sensor/firmware interplay on a breadboard — not full drive mode, just
whether the chosen sensors, the Pi-ESP32 link, and the existing
`papaya_mission` software actually work together on real hardware. This is
the second of two supporting pieces the user wanted before the ESP32
firmware plan (the first, the digital-twin simulator, is merged) — see
project memory `project-esp32-testing-strategy`.

## Decisions made so far

| Question | Decision |
|---|---|
| ESP32 unit | A separate, dedicated spare ESP32-S3 dev board — not the real Phase 1 rover's unit. Zero risk to the working build; new firmware written from scratch, nothing shared with the real rover's firmware. |
| ESP32 scope this pass | Included, not deferred: bump sensor(s) + I2C GPIO-expander + a first real Pi↔ESP32 link, directly serving "informs the real wire protocol." |
| Pi↔ESP32 link medium | UART — already implied by the approved OTA design ("the Pi flashes the ESP32 over the existing serial link using the same protocol a USB-connected laptop uses today," i.e. esptool-class flashing, which is inherently UART). |
| Software scope | Real `SensorHub`/`Esp32Link` Protocol-conforming drivers, run through the actual, already-tested `MissionRuntime` — the same role `SimulatedSensorHub` and the digital twin played, now backed by real hardware. Not throwaway bring-up scripts. |
| Compute | Raspberry Pi 5 (4GB or 8GB, both on hand), NVMe HAT available. Owns all sensing (GPS/IMU/ultrasonic/camera) + mission logic, per D-6. |
| Camera | Raspberry Pi AI Camera (v1 confirmed on hand), CSI connector, no GPIO. |
| Ultrasonic | 4Tronix-mast-bundled HC-SR04-class unit. Pi-managed via GPIO trigger/echo + `pigpio`. **ECHO is 5V — requires a 2-resistor voltage divider (1k/2k) before reaching the Pi GPIO; never direct.** |
| GPS | SparkFun NEO-M9N (SMA), wired via its **UART** pins (not its Qwiic/I2C option) — validates the intended long-term interface and keeps GPS traffic off the IMU/LCD I2C bus. |
| IMU | Wired **one at a time**, not simultaneously: Adafruit BNO055 active/first (onboard fusion → fastest path to a working `heading_deg`); SparkFun ICM-20948 documented as a direct swap-in (same 4 points) for comparison. Both NRND parts — fine for this bench eval, not the permanent PCB (see `feedback-verify-part-lifecycle-before-purchase`). |
| LCD | Pi-managed, I2C. Assumed working default (confirm later): 16x2 character LCD + PCF8574 backpack (addr `0x27` or `0x3F`), powered at 5V. Screens driven from the same state `MissionRuntime` already assembles into telemetry each tick. |
| LCD navigation | Up/down buttons cycle screens; 2 function buttons whose meaning depends on the current screen (soft-key style, not fixed). All 4 buttons wired to GND, debounced via the Pi's internal GPIO pull-ups (no external resistor). |
| Throttle simulator | A potentiometer into an ESP32 ADC pin, reported via `read_drive_status`, mapped to `0.0`–`1.0` (forward-only; the full `-1.0..1.0` reverse range is deferred, not needed to validate the round-trip). |
| Spare ELRS controller | **Explicitly excluded from this pass.** Nothing in `MissionRuntime` commands throttle today — it only reads `drive_status` — so human-driven ELRS input wouldn't exercise anything new; it would just re-prove ELRS decoding, which the real Phase 1 firmware already does. Relevant again once a real Pi→ESP32 autonomous drive-command channel exists and manual-override arbitration becomes a real design question (see the inbox note on manual override). |
| Bump sensors (bench) | 2 switches (left/right) via a PCF8574 I2C GPIO-expander on the ESP32's own I2C bus (separate from the Pi's). PCF8574's built-in weak pull-ups mean each switch wires directly to GND, no external resistor. INT line to an ESP32 interrupt-capable GPIO for immediate response. |
| Bump sensors (production, logged not decided) | Likely 4 axle corners, possibly also payload-bay corners — depends on whether SEN-1's ultrasonic vertical beam cone already covers that height. Plan: empirically map the real cone on this breadboard (move a target vertically at a few distances, record where detection drops out) rather than estimate from a datasheet. |
| ESP32 firmware toolchain | Arduino framework (`.ino`), matching the real Phase 1 firmware's own convention. |
| Pi↔ESP32 message pattern | Periodic heartbeat (~150ms: halted flag + throttle) + eager push the instant a bump occurs — not request/response. Commands from the Pi (geofence update, OTA trigger) are one-way, fire-and-forget; nothing in `Esp32Link`'s existing signatures expects a blocking reply. |
| Message format | Newline-delimited JSON, one `type` field per line. |
| OTA mechanism (this pass) | No custom firmware cooperation needed: standard ESP32 dev boards already auto-enter their bootloader via the USB-serial chip's DTR/RTS lines, which is exactly what `esptool.py` does automatically. `trigger_ota()` just releases the Pi's serial connection, shells out to `esptool.py` against that port, and reopens the connection once the board reboots. Proves the real mechanism (no cable swap) without an in-firmware OTA state machine. |
| OTA safety gating (logged, not built here) | "WiFi in range" is already structurally guaranteed (can't have a firmware file without having downloaded it over WiFi). "No mission underway": Pi-side `SweepSession`-active check is the straightforward answer; a true device-level veto conflicts with this pass's auto-reset OTA mechanism (nothing in firmware is consulted) and is deferred to the ESP32 firmware plan. |
| Driver testability | `hardware_sensor_hub.py`/`hardware_esp32_link.py` accept their low-level transport (serial/I2C object) as a constructor argument rather than constructing it internally, so message framing, the bump-event queue, cached status, pot-to-throttle mapping, LCD screen content, and button dispatch are all genuinely unit-testable (TDD, same as the rest of this codebase) against an in-memory fake transport. Only the thin real-I/O calls themselves fall outside that — verified by the bring-up checklist instead. |
| Power domains | Pi and ESP32 have independent power supplies (separate USB sources) but **must share a common ground** for the UART link to be reliable. |
| Breadboard 5V source | The Pi's own 5V GPIO pin — combined ultrasonic + LCD draw is well under 150mA, trivial against the Pi 5's supply budget. Scoped to this breadboard only; the real PCB will likely reuse the existing U2 UBEC 5V rail instead (a later decision, not in conflict — see `pathfinder/papaya-wiring-layout.yaml`'s `u2`). |
| Wiring-file convention | New `docs/wiring/` directory holds all non-"real rover" wiring snapshots, named descriptively (not version-numbered) — this breadboard first, future per-mission-package builds later. The root `papaya-wiring-layout.yaml` (real Phase 1 rover) is untouched; it's referenced by name in 3 KiCad generator scripts and 6 docs. `generate_schematic.py`/`sync_pin_names.py` already take `--yaml PATH` and work unmodified against any file following the same schema; `assign_footprints.py` is a Phase-1-specific one-off (hardcodes footprint content, not just paths) and isn't meant to generalize. |

## Architecture

Two physically separate units, each independently powered, tied together
by one UART link and a shared ground:

```
┌─────────────────────────┐         UART (TX/RX)        ┌──────────────────────────┐
│       Raspberry Pi 5      │◄───────────────────────────►│   ESP32-S3 dev board      │
│                           │         + shared GND         │   (bench-dedicated)       │
│  MissionRuntime           │                              │                           │
│   ├─ hardware_sensor_hub  │                              │  New firmware (.ino):     │
│   │   GPS (UART)          │                              │   - PCF8574 bump sensing  │
│   │   IMU (I2C)           │                              │     (I2C + INT)           │
│   │   Ultrasonic (GPIO +  │                              │   - Pot ADC read          │
│   │     pigpio, divider)  │                              │   - UART heartbeat/push   │
│   │   Camera (CSI)        │                              │   - halted-state LED      │
│   ├─ hardware_esp32_link  │                              │                           │
│   │   (UART, NDJSON)      │                              │  OTA: esptool's own       │
│   └─ status_display       │                              │  DTR/RTS auto-reset,      │
│       LCD + 4 buttons     │                              │  no firmware cooperation  │
│       (I2C + GPIO)        │                              │  needed this pass         │
└─────────────────────────┘                              └──────────────────────────┘
```

No custom PCB in this build — see `docs/wiring/breadboard-wiring-layout.yaml`
for the full pin-level netlist (17 components, cross-validated so every
connection references a real component/pin). The physical breadboard
placement diagram (which rows on which board, how to combine the 30-pin/
63-pin boards on hand) is a separate, later step, done only once every pin
assignment above is settled — so it only needs to be drawn once.

## File structure

```
pathfinder-autonomous/pi-mission/papaya_mission/
  hardware_sensor_hub.py   # NEW -- real GpsSource/ImuSource/UltrasonicSource/
                           #        CameraSource implementations. Transport/bus
                           #        objects injected via constructor for testability.
  hardware_esp32_link.py   # NEW -- real Esp32Link implementation over UART
                           #        (NDJSON heartbeat + eager push). Serial
                           #        object injected via constructor.
  status_display.py        # NEW -- LCD + button screens. Reads the same
                           #        state MissionRuntime assembles into
                           #        telemetry each tick; no separate data path.

esp32-firmware/            # NEW -- first firmware in this repo
  papaya_bench/papaya_bench.ino
```

## Pi↔ESP32 wire protocol

Newline-delimited JSON, one `type` field per line. Every `Esp32Link`
method is exercised, though not all equally "real" on a rig with no
drivetrain:

| Method | Breadboard behavior |
|---|---|
| `poll_bump_events` | Fully real: PCF8574 INT → debounced in firmware → pushed immediately as `{"type": "bump", "ts_ms": ...}`. Pi-side driver queues it; `ts_ms` is for latency/ordering diagnostics only — the Pi still assigns its own wall-clock `detected_at` on receipt, matching how `BumpEvent` already works elsewhere. |
| `status` | Fully real: ESP32's own `halted` flag, set by the same bump interrupt, included in every heartbeat line (`{"type": "status", "halted": bool, "throttle": float}`). Also drives the bench-visible halted-state LED. |
| `read_drive_status` | Real wire format, pot-driven value: `throttle` in the same heartbeat line, mapped from the ADC pin to `0.0`–`1.0`. |
| `send_geofence_update` | Placeholder effect, real message: `{"type": "geofence_update", "zone_ids": [...]}` sent Pi→ESP32, acknowledged with a log line only — no drivetrain to act on it here. |
| `trigger_ota` | Fully real, simplified: no message to the firmware at all this pass — the Pi releases its serial connection and invokes `esptool.py` directly against the shared port, relying on the dev board's standard DTR/RTS auto-reset. |

## Testing & bring-up

**Design for testability:** both driver modules accept their low-level
transport (a `serial.Serial`-like object, an I2C bus object) as a
constructor argument rather than constructing it internally. That makes
message encode/decode, the bump-event queue, cached status, the
pot-to-throttle mapping, LCD screen content per state, and button-to-action
dispatch all genuinely unit-testable — TDD, same as the rest of this
codebase — against an in-memory fake transport (a plain list of strings
standing in for serial lines). Only the thin real `pyserial`/`smbus2` calls
themselves fall outside that, and are deliberately kept as small as
possible.

**Bring-up checklist** (staged, one piece at a time, so a failure is always
localized to whatever was just added):

1. Power-on smoke test — Pi and ESP32 alone, nothing attached yet
2. Pi↔ESP32 UART link — just TX/RX/GND, confirm heartbeat JSON arrives
3. Bump sensor + PCF8574 — confirm a switch press produces a bump message
4. Pot — confirm turning it changes the reported throttle value
5. OTA — a trivial firmware change (e.g. blink rate), prove the
   `esptool`-over-shared-port reflash actually works
6. GPS, then IMU (BNO055 first), then ultrasonic (including the vertical-
   cone test), then camera, then LCD+buttons — each wired and verified alone
7. Only once every piece is individually proven: wire in the real
   `SensorHub`/`Esp32Link` implementations and run the actual
   `MissionRuntime` against them end-to-end

## Out of scope (for this project)

- **LEDs simulating servo/BTS motor-controller output.** The bench ESP32
  runs entirely new firmware with no servo/motor-control logic in it —
  nothing would genuinely drive such LEDs, and porting the real Phase 1
  firmware's PWM logic over would just re-prove already-working code for no
  new information. The one LED this plan does include (halted-state) is
  justified because it reflects a real, newly-computed value on this board.
- **Real ESP32 GPIO-headroom check for the eventual production board.** Once
  bump-I2C + Pi-UART get folded into the *real* rover's ESP32 alongside its
  existing servo/motor/ELRS pins, a concrete pin-count check against the
  real ESP32-S3's available GPIO is worth doing — already anticipated in
  the existing design notes (CON-B4), not a breadboard concern since this
  bench ESP32 is a fully separate, unconstrained board. Deferred to the
  ESP32 firmware plan.
- **In-firmware OTA cooperation / device-level safety veto.** This pass's
  OTA validation relies entirely on `esptool`'s standard auto-reset, which
  bypasses the running firmware. A cooperative handshake (Pi asks "safe to
  flash?", firmware acks/nacks based on its own mission-active state) would
  be needed for a genuine device-level veto and is deferred to the ESP32
  firmware plan, where OTA sophistication is already expected to grow.
- **Training mode (recovery-maneuver telemetry capture)** and **manual
  drive override via LCD + spare ELRS controller** — both logged in the
  phase2 inbox, neither designed or built here. The override idea reserves
  an LCD screen/function-key slot for later; training mode's
  capability-vs-mission-package framing is left open.
- **Exact LCD part, exact bump-switch count beyond 2, exact IMU choice
  between the two bench candidates.** All left as explicit, swappable
  placeholders — see `docs/wiring/breadboard-wiring-layout.yaml`.
