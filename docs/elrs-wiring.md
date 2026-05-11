# ELRS Receiver Wiring & Radio Setup

This document covers wiring the RadioMaster ELRS-RP3-V2 receiver to the ESP32-S3,
binding it to the BETAFPV LiteRadio 2 SE transmitter, and understanding how the
firmware maps RC channels to rover controls.

---

## Hardware Used

| Component | Model |
|---|---|
| Microcontroller | ESP32-S3 |
| RC Receiver | RadioMaster ELRS-RP3-V2 (2.4 GHz ELRS V3) |
| RC Transmitter | BETAFPV LiteRadio 2 SE (2.4 GHz ELRS V3) |
| Firmware | `pathfinder/firmware-elrs/firmware-elrs.ino` |

---

## Receiver Wiring (RP3-V2 → ESP32-S3)

The firmware communicates with the receiver over CRSF serial protocol using
HardwareSerial port 2 at 420,000 baud. The serial pins are defined in the firmware:

```cpp
#define RX_PIN 47   // ESP32 receives data FROM receiver (green wire)
#define TX_PIN 21   // ESP32 sends telemetry TO receiver (white wire)
```

Neither pin conflicts with the motor driver or servo pins already assigned.

### Wire Connections

| Wire color | Receiver label | ESP32-S3 pin |
|---|---|---|
| Red | VCC | 5V |
| Black | GND | GND |
| Green | TX (receiver output) | GPIO 47 |
| White | RX (receiver input) | GPIO 21 |

> **Note on cross-connection:** The receiver's TX (green) connects to the ESP32's
> RX pin, and the receiver's RX (white) connects to the ESP32's TX pin. This
> cross-connect is standard for any UART serial link.

> **Logic level:** The RP3-V2 outputs 3.3V logic on its signal lines even when
> powered from 5V. Connecting directly to ESP32-S3 GPIO pins is safe — no level
> shifter required.

### Already-Assigned ESP32 Pins (for reference)

| GPIO | Assignment |
|---|---|
| 7 | Servo #2 (white signal wire) |
| 10 | BTS #2 – pin 1 |
| 11 | BTS #2 – pin 2 |
| 12 | BTS #1 – pin 1 |
| 13 | BTS #1 – pin 2 |
| 21 | ELRS receiver RX (white wire) ← new |
| 38 | Servo #4 (white signal wire) |
| 41 | Servo #3 (white signal wire) |
| 42 | Servo #1 (white signal wire) |
| 47 | ELRS receiver TX (green wire) ← new |
| 48 | Onboard RGB LED (firmware-managed) |

---

## Binding the Transmitter and Receiver

Both devices run ELRS 2.4 GHz V3 and are fully compatible. Two binding methods
are available.

### Method 1: Binding Phrase (Recommended)

The modern ELRS approach — both devices share a passphrase and connect
automatically on power-up, no button press required.

1. Download and install **ExpressLRS Configurator**:
   `https://github.com/ExpressLRS/ExpressLRS-Configurator/releases`

2. Flash the **RP3-V2 receiver** via the Configurator:
   - Target: `RadioMaster 2.4GHz RP3-V2`
   - Set a binding phrase (e.g. `myrover2024`) — keep this private
   - Flash via WiFi or UART passthrough

3. Configure the **LiteRadio 2 SE transmitter**:
   - Power on the transmitter
   - Press `SYS` → scroll to `ExpressLRS` Lua script → open it
   - Navigate to `Binding Phrase` and enter the same phrase
   - Save and reboot

4. Power both devices on — they connect automatically. No further binding needed.

### Method 2: Traditional Button Bind

Use this if you prefer not to reflash the receiver with a custom binding phrase.

1. Power on the LiteRadio 2 SE transmitter
2. Hold the **bind button on the RP3-V2** while plugging in receiver power
   — the receiver LED flashes rapidly to indicate bind mode
3. On the transmitter: `SYS → ExpressLRS Lua script → [BIND]`
4. The receiver LED goes solid — binding is complete

---

## RC Channel Mapping

The firmware reads three CRSF channels and maps them to rover functions:

| CRSF Channel | Rover Function | LiteRadio 2 SE stick (Mode 2) |
|---|---|---|
| Ch 1 | Steering — left/right | Right stick, horizontal |
| Ch 3 | Throttle — forward/reverse | Left stick, vertical |
| Ch 4 | Spin in place | Right stick, vertical |

The LiteRadio 2 SE ships in Mode 2 by default, so no transmitter reconfiguration
is needed.

Spin mode activates only when Ch 4 is deflected **and** throttle and steering are
both within the deadzone (±10% of center). See
[firmware-elrs.ino lines 98-105](../pathfinder/firmware-elrs/firmware-elrs.ino#L98-L105).

---

## Required Arduino Libraries

Install both libraries in Arduino IDE before uploading the firmware:

| Library | Purpose | Install via |
|---|---|---|
| `AlfredoCRSF` | CRSF serial protocol for ELRS | Arduino Library Manager |
| `Adafruit NeoPixel` | Onboard RGB status LED | Arduino Library Manager |

**Tools → Manage Libraries → search by name → Install**

---

## LED Status Indicators

The firmware uses the onboard RGB LED (GPIO 48) to indicate link state:

| LED color | Meaning |
|---|---|
| White | Startup / initializing |
| Green | Transmitter link is active |
| Red | Waiting for transmitter signal |
