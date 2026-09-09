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
are available. **Neither device has a screen** — the LiteRadio 2 SE is a
gamepad-style transmitter (no OpenTX/EdgeTX menu system) and the RP3-V2 is a
bare chip-scale receiver, so both binding methods below rely on physical
buttons/power-cycling, not on-screen menus.

### Method 2: Traditional Button Bind (Recommended here)

Uses each device's factory-default identity (RP3-V2 ships with no binding
phrase set — it binds via chip ID). **No PC software required at all**, which
makes this the path to use if the BETAFPV Configurator or ExpressLRS
Configurator is giving you trouble.

> **Gotcha, confirmed on this build:** a receiver that has ever been flashed
> with a binding phrase (Method 1) **will not enter manual bind mode at
> all**, even though its LED may still change patterns in a way that looks
> like it's searching. If Method 2 isn't working and the receiver was ever
> given a custom phrase, go clear it first: reconnect to the receiver's WiFi
> config page (or ExpressLRS Configurator) and **delete the binding phrase
> field so it's genuinely blank**, then save/reflash, before retrying the
> steps below. This was the actual root cause the first time through this
> procedure on this build — the receiver had a phrase set but the
> transmitter (see Method 1's compatibility note below) never got a
> matching one, so nothing could ever pair no matter how the button-bind
> timing was adjusted.

1. Put the **RP3-V2 receiver** into bind mode: power it on, then rapidly
   power-cycle it 3 times in quick succession (unplug/replug receiver power
   three times, each off-period under ~2 seconds). Its LED should
   double-blink quickly to confirm bind mode. (It has no physical bind
   button — this power-cycle sequence is the substitute.)
2. Put the **LiteRadio 2 SE transmitter** into bind mode: power it on, then
   press the **Bind button** once — a small recessed button on the
   transmitter body **to the left of its USB charging port**, distinct from
   the 4 AUX toggle switches on the front. Its LED flashes red to confirm
   bind mode.
3. Within a few seconds the two should pair — the receiver's LED goes solid
   to confirm binding is complete.

### Method 1: Custom Binding Phrase (not usable on this build — reference only)

Lets you set a memorable private phrase instead of relying on the RP3-V2's
factory chip ID — mainly useful if other ELRS gear might be nearby and you
want to guarantee no cross-binding. More involved than it sounds: the
LiteRadio 2 SE has no menu to type a phrase into directly, so **BETAFPV
Configurator** is required to set it on the transmitter side, and the
resulting UID bytes then have to be entered manually into the receiver via
its CLI.

**Confirmed not usable on this build's transmitter unit**: this specific
LiteRadio 2 SE is missing the sticker BETAFPV uses to mark units compatible
with their Configurator software, and setting a phrase on the receiver only
(with no way to match it on the transmitter) is what caused the extended
bind failure documented in Method 2's callout above. Left here for
reference in case a compatible transmitter is used in the future — use
Method 2 for this build.

1. Download and install **BETAFPV Configurator**:
   `https://github.com/BETAFPV/BETAFPV_Configurator/releases`
2. In the Configurator, set a binding phrase for the LiteRadio 2 SE, save,
   and reboot the transmitter. Note the UID bytes the Configurator
   generates from your phrase.
3. Flash the **RP3-V2 receiver** via **ExpressLRS Configurator**
   (`https://github.com/ExpressLRS/ExpressLRS-Configurator/releases`,
   a separate tool from BETAFPV Configurator) using its WiFi method — the
   receiver hosts its own access point (`ExpressLRS RX`, password
   `expresslrs`) after ~60 seconds unbound; connect to it and browse to
   `http://10.0.0.1`. Enter the same binding phrase there, or if only UID
   bytes are supported, enter those bytes via the receiver's Betaflight CLI.
4. Power both devices on — they connect automatically.

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
