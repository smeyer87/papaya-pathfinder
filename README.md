# Papaya Pathfinder — Personal Build

<div style="text-align: center;">
  <img src="patch.png" alt="Papaya Pathfinder patch" width="250"/>
</div>

This is a personal fork of the open-source [Papaya Pathfinder](https://github.com/tronxi/papaya-pathfinder)
rover project, building the **full-size Pathfinder** with custom electronics
and a from-scratch PCB design. It is not a general-purpose reference for the
upstream project — for that (both rover variants, the Android/desktop
controllers, full parts lists, licensing), see the archived
[upstream README](docs/UPSTREAM_README.md).

This fork intentionally does **not** use `pathfinder-mini`,
`android-controller`, or `desktop-controller` — control is via a standard
R/C transmitter/receiver instead.

## Hardware

- **Controller:** ESP32-S3
- **Radio:** RadioMaster ELRS-RP3-V2 receiver + BETAFPV LiteRadio 2 SE
  transmitter (ELRS V3, 2.4 GHz) — not covered by the upstream project;
  see [`docs/elrs-wiring.md`](docs/elrs-wiring.md)
- **Motor Drivers:** 2× BTS7960/IBT_2
- **Motors:** 6× GA25 DC gear motors (3 per side, ganged — one PWM signal
  per side drives all 3 motors on that side simultaneously)
- **Steering:** 4× MS24 servos (front and rear axles only)
- **Power:** LiPo 3S
- **Voltage Regulation:** UBEC 5V/3A (logic) + UBEC 6V/8A (servos)

Full mechanical parts list and 3D-printable files are unchanged from
upstream — see the [3D-Printed Parts table](docs/UPSTREAM_README.md#3d-printed-parts)
and [`pathfinder/3d-models/`](pathfinder/3d-models/).

## Electronics & PCB design (this fork's main addition)

The stock electronics were originally point-to-point soldered onto a
pre-drilled prototyping board. That's being replaced with a custom PCB,
designed via a YAML-first workflow rather than starting cold in KiCad:

- **[`papaya-wiring-layout.yaml`](papaya-wiring-layout.yaml)** — the single
  source of truth for the *entire* electrical system (battery, fuse,
  switch, terminal blocks, motor drivers, UBECs, ESP32, ELRS receiver,
  motors, servos, and the board's own connectors), not just the board.
  Real wire gauges, real terminal numbering, ground loop verified closed.
- **[`pathfinder/kicad/papaya-pcb/`](pathfinder/kicad/papaya-pcb/)** — the
  KiCad 10 project. The schematic is generated (see below), not hand-drawn.
- **[`pathfinder/kicad/scripts/generate_schematic.py`](pathfinder/kicad/scripts/generate_schematic.py)** —
  reads the wiring YAML and writes a fully-wired starter schematic (every
  component placed, every net labeled), validated against real KiCad 10 with
  zero ERC errors. Re-run it any time the YAML changes:
  ```
  pip install -r pathfinder/kicad/scripts/requirements.txt
  python pathfinder/kicad/scripts/generate_schematic.py
  ```

See **[`docs/development-log.md`](docs/development-log.md)** for the full
write-up of how the wiring model and generator were built, what got
corrected along the way, and what's left.

## Documentation

- [`docs/build-notes.md`](docs/build-notes.md) — build journal, gap
  analysis vs. the upstream docs, project goals for this fork
- [`docs/elrs-wiring.md`](docs/elrs-wiring.md) — ELRS receiver wiring,
  binding, and RC channel mapping
- [`docs/development-log.md`](docs/development-log.md) — wiring model and
  KiCad generator development summary
- [`docs/UPSTREAM_README.md`](docs/UPSTREAM_README.md) — archived original
  project README (both rover variants, full parts tables, controllers)

## License

This project is licensed under the **Apache License 2.0** — see
[LICENSE](LICENSE). This fork is derived from
[tronxi/papaya-pathfinder](https://github.com/tronxi/papaya-pathfinder);
see [`docs/UPSTREAM_README.md`](docs/UPSTREAM_README.md) for original
project attribution.
