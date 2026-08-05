#!/usr/bin/env python3
"""Assign real footprints to board-main's connector groups.

Patches two places (both insert-only, never rewrites existing content):
  1. papaya-wiring-layout.yaml -- adds `footprint: "..."` inside each
     board-main connectionPoint's existing `connector: {...}` block, keyed
     by id prefix (e.g. all "J_ESP32.*" points get the same footprint,
     since they're one physical connector).
  2. The live .kicad_sch -- sets each matching symbol instance's empty
     `Footprint` property directly, so the assignment is visible in KiCad
     without you re-running Assign Footprints by hand.

FOOTPRINTS below were matched against the real KiCad 10 library on this
machine (see BOM.md for the underlying parts) -- not guessed from memory.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
YAML_PATH = REPO_ROOT / "papaya-wiring-layout.yaml"
SCH_PATH = REPO_ROOT / "pathfinder" / "kicad" / "papaya-pcb" / "papaya-pcb.kicad_sch"

TERM_2POS = "TerminalBlock:TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm"
SOCKET_2x22 = "papaya-pcb:ESP32S3_DevKit_2x1x22_split"  # custom: real board is two separate 1x22 rows, not one 2x22 block
UBEC_CUSTOM = "papaya-pcb:UBEC_5V_3A_10x15mm"
# The three below are custom pad-renamed copies of standard parts -- the
# standard library's default sequential pad numbering ("1".."6", etc.)
# doesn't match our schematic's actual pin names (e.g. BTS driver pins
# skip 5/6; ELRS/servo pins are named, not numbered). See
# scripts/_gen_renamed_footprints.py for how these were derived.
BTS_SIGNAL = "papaya-pcb:PinHeader_1x06_BTS_Signal"  # pads: 1,2,3,4,7,8
ELRS_HDR = "papaya-pcb:PinHeader_1x04_ELRS"  # pads: VCC,GND,TX,RX
UBEC6V_TERM = "papaya-pcb:TerminalBlock_2Pos_UBEC6V"  # pads: OUTP,OUTN
SERVO_HDR = "papaya-pcb:PinHeader_1x03_Servo"  # pads: GND,PWR,SIG

# id prefix -> footprint (used for the YAML patch)
PREFIX_FOOTPRINT = {
    "J1": TERM_2POS,
    "J_ESP32": SOCKET_2x22,
    "J_UBEC5V": UBEC_CUSTOM,
    "J_BTS1": BTS_SIGNAL,
    "J_BTS2": BTS_SIGNAL,
    "J_ELRS": ELRS_HDR,
    "J_GND_MASTER": TERM_2POS,
    "J_UBEC6V": UBEC6V_TERM,
    "J_S1": SERVO_HDR,
    "J_S2": SERVO_HDR,
    "J_S3": SERVO_HDR,
    "J_S4": SERVO_HDR,
}

# ref designator (as assigned by generate_schematic.py, in first-appearance
# order of the prefixes above) -> footprint (used for the .kicad_sch patch)
REF_FOOTPRINT = {
    "J1": TERM_2POS,
    "J2": SOCKET_2x22,
    "J3": UBEC_CUSTOM,
    "J4": BTS_SIGNAL,
    "J5": BTS_SIGNAL,
    "J6": ELRS_HDR,
    "J7": TERM_2POS,
    "J8": UBEC6V_TERM,
    "J9": SERVO_HDR,
    "J10": SERVO_HDR,
    "J11": SERVO_HDR,
    "J12": SERVO_HDR,
}

TOP_COMPONENT_RE = re.compile(r"^  - id: (\S+)\s*$")
POINT_ID_RE = re.compile(r"^\s+- id: (\S+)\s*$")
CONNECTOR_RE = re.compile(r"^(\s*)connector: \{(.*)\}\s*$")


def patch_yaml(text: str) -> tuple[str, int]:
    lines = text.splitlines(keepends=True)
    out = []
    current_comp = None
    current_prefix = None
    count = 0
    for line in lines:
        stripped = line.rstrip("\r\n")
        m_top = TOP_COMPONENT_RE.match(stripped)
        if m_top:
            current_comp = m_top.group(1)
            out.append(line)
            continue
        if current_comp == "board-main":
            m_pt = POINT_ID_RE.match(stripped)
            if m_pt:
                point_id = m_pt.group(1)
                current_prefix = point_id.split(".", 1)[0] if "." in point_id else point_id
                out.append(line)
                continue
            m_conn = CONNECTOR_RE.match(stripped)
            if m_conn and current_prefix in PREFIX_FOOTPRINT:
                indent, inner = m_conn.groups()
                fp = PREFIX_FOOTPRINT[current_prefix]
                inner = inner.strip()
                if inner.endswith(","):
                    inner = inner[:-1]
                existing_fp = re.search(r',?\s*footprint: "[^"]*"', inner)
                if existing_fp:
                    inner = inner[: existing_fp.start()] + inner[existing_fp.end() :]
                    inner = inner.rstrip().rstrip(",")
                new_line = f'{indent}connector: {{{inner}, footprint: "{fp}" }}\n'
                out.append(new_line)
                count += 1
                continue
        out.append(line)
    return "".join(out), count


REF_LINE_RE = re.compile(r'^\s*\(property "Reference" "([^"]+)"')
FOOTPRINT_LINE_RE = re.compile(r'^(\s*)\(property "Footprint" "[^"]*"')


def patch_sch(text: str) -> tuple[str, int]:
    lines = text.splitlines(keepends=True)
    out = []
    pending_ref = None
    count = 0
    for line in lines:
        stripped = line.rstrip("\r\n")
        m_ref = REF_LINE_RE.match(stripped)
        if m_ref and m_ref.group(1) in REF_FOOTPRINT:
            pending_ref = m_ref.group(1)
            out.append(line)
            continue
        m_fp = FOOTPRINT_LINE_RE.match(stripped)
        if m_fp and pending_ref:
            indent = m_fp.group(1)
            fp = REF_FOOTPRINT[pending_ref]
            new_line = f'{indent}(property "Footprint" "{fp}"\n'
            out.append(new_line)
            count += 1
            pending_ref = None
            continue
        out.append(line)
    return "".join(out), count


def main():
    yaml_text = YAML_PATH.read_text(encoding="utf-8", newline="")
    new_yaml, yaml_count = patch_yaml(yaml_text)
    YAML_PATH.write_text(new_yaml, encoding="utf-8", newline="")
    print(f"YAML: added footprint to {yaml_count} connector blocks")

    sch_text = SCH_PATH.read_text(encoding="utf-8", newline="")
    new_sch, sch_count = patch_sch(sch_text)
    SCH_PATH.write_text(new_sch, encoding="utf-8", newline="")
    print(f"Schematic: set Footprint on {sch_count} symbol instances")


if __name__ == "__main__":
    main()
