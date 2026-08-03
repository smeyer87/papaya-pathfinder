#!/usr/bin/env python3
"""Sync pin names edited in KiCad's schematic editor back into the wiring YAML.

Reads the current .kicad_sch's embedded symbol pin names and inserts a
`kicadPinName` line next to each connectionPoint's existing `label` in
papaya-wiring-layout.yaml (label stays as the fuller descriptive text).
generate_schematic.py prefers `kicadPinName` when present, so future
regenerations won't clobber names you've tightened up for on-screen
legibility.

This is a pure text patcher (line-by-line insertion only) rather than a
full YAML re-serialize -- a round-trip through PyYAML or ruamel.yaml would
reformat/relocate this file's hand-maintained comments. It never rewrites
an existing line, only inserts new ones, so nothing else in the file can
be touched.

Usage:
    python sync_pin_names.py [--yaml PATH] [--sch PATH] [--dry-run]
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

from generate_schematic import build_placements
from kicad_sexpr import extract_pin_names

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_YAML = REPO_ROOT / "papaya-wiring-layout.yaml"
DEFAULT_SCH = REPO_ROOT / "pathfinder" / "kicad" / "papaya-pcb" / "papaya-pcb.kicad_sch"

TOP_COMPONENT_RE = re.compile(r"^  - id: (\S+)\s*$")
BLOCK_POINT_RE = re.compile(r"^(\s+)- id: (\S+)\s*$")
LABEL_RE = re.compile(r"^(\s+)label:")
COMPACT_ONELINE_RE = re.compile(r'^(\s*)- \{.*\bid:\s*"?([^,"\s}]+)"?,.*\}\s*$')
COMPACT_OPEN_RE = re.compile(r"^(\s*)- \{\s*$")
COMPACT_ID_RE = re.compile(r'^\s*id:\s*"?([^,"\s}]+)"?,?\s*$')
COMPACT_LABEL_RE = re.compile(r"^(\s+)label:.*,\s*$")
COMPACT_CLOSE_RE = re.compile(r"^(\s*)\},?\s*$")


def esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def patch(text: str, wanted: dict) -> tuple[str, int, list]:
    """wanted: {(comp_id, point_id): kicad_pin_name}. Returns (new_text, count, unmatched_keys)."""
    lines = text.splitlines(keepends=True)
    out = []
    current_comp = None
    matched = set()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.rstrip("\r\n")

        if stripped == "connections:":
            out.append(line)
            out.extend(lines[i + 1 :])
            i = n
            break

        m_top = TOP_COMPONENT_RE.match(stripped)
        if m_top:
            current_comp = m_top.group(1)
            out.append(line)
            i += 1
            continue

        m_one = COMPACT_ONELINE_RE.match(stripped)
        if m_one and current_comp:
            point_id = m_one.group(2)
            key = (current_comp, point_id)
            if key in wanted:
                matched.add(key)
                closing = stripped.rstrip()
                assert closing.endswith("}")
                inner = closing[:-1].rstrip()
                if inner.endswith(","):
                    new_line = f'{inner} kicadPinName: "{esc(wanted[key])}" }}\n'
                else:
                    new_line = f'{inner}, kicadPinName: "{esc(wanted[key])}" }}\n'
                out.append(new_line)
                i += 1
                continue
            out.append(line)
            i += 1
            continue

        m_open = COMPACT_OPEN_RE.match(stripped)
        if m_open and current_comp:
            block = [line]
            j = i + 1
            point_id = None
            while j < n:
                bl = lines[j]
                bstripped = bl.rstrip("\r\n")
                block.append(bl)
                m_id = COMPACT_ID_RE.match(bstripped)
                if m_id:
                    point_id = m_id.group(1)
                if COMPACT_CLOSE_RE.match(bstripped):
                    j += 1
                    break
                j += 1
            key = (current_comp, point_id) if point_id else None
            if key in wanted:
                matched.add(key)
                close_idx = len(block) - 1
                indent = COMPACT_CLOSE_RE.match(block[close_idx].rstrip("\r\n")).group(1)
                insert_line = f'{indent}  kicadPinName: "{esc(wanted[key])}",\n'
                block = block[:close_idx] + [insert_line] + block[close_idx:]
            out.extend(block)
            i = j
            continue

        m_block = BLOCK_POINT_RE.match(stripped)
        if m_block and current_comp:
            point_indent, point_id = m_block.groups()
            key = (current_comp, point_id)
            block = [line]
            j = i + 1
            label_idx = None
            while j < n:
                bl = lines[j]
                bstripped = bl.rstrip("\r\n")
                if bstripped.strip() == "" or len(bstripped) - len(bstripped.lstrip()) > len(point_indent):
                    if LABEL_RE.match(bstripped):
                        label_idx = len(block)
                    block.append(bl)
                    j += 1
                    continue
                break
            if key in wanted:
                matched.add(key)
                label_indent = point_indent + "  "
                insert_line = f'{label_indent}kicadPinName: "{esc(wanted[key])}"\n'
                insert_at = label_idx + 1 if label_idx is not None else 1
                block = block[:insert_at] + [insert_line] + block[insert_at:]
            out.extend(block)
            i = j
            continue

        out.append(line)
        i += 1

    unmatched = [k for k in wanted if k not in matched]
    return "".join(out), len(matched), unmatched


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--yaml", type=Path, default=DEFAULT_YAML)
    ap.add_argument("--sch", type=Path, default=DEFAULT_SCH)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    original = args.yaml.read_text(encoding="utf-8", newline="")
    plain_data = yaml.safe_load(original)
    _, pin_lookup = build_placements(plain_data)
    kicad_pins = extract_pin_names(args.sch)

    wanted = {}
    for key, (ref, pin_num) in pin_lookup.items():
        name = kicad_pins.get(ref, {}).get(pin_num)
        if name is not None:
            wanted[key] = name

    new_text, count, unmatched = patch(original, wanted)

    print(f"Would insert/would have inserted: {count} kicadPinName fields.")
    if unmatched:
        print(f"Unmatched (not found in text patcher, needs review): {len(unmatched)}")
        for k in unmatched[:20]:
            print("  ", k)

    if args.dry_run:
        out_path = args.yaml.parent / "papaya-wiring-layout.PATCHED_PREVIEW.yaml"
        out_path.write_text(new_text, encoding="utf-8", newline="")
        print(f"Dry run: wrote preview to {out_path}")
    else:
        args.yaml.write_text(new_text, encoding="utf-8", newline="")
        print(f"Wrote {args.yaml}")


if __name__ == "__main__":
    main()
