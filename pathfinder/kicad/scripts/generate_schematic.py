#!/usr/bin/env python3
"""Generate a starter KiCad schematic from papaya-wiring-layout.yaml.

Reads the system-level wiring YAML and writes a fully-wired starter
.kicad_sch: every component becomes a schematic symbol, every connection
and bondedGroup becomes a matching net label. Symbols/footprints for parts
without an official KiCad library entry are generated as generic labeled
boxes with one pin per connectionPoint, embedded directly in the output
file (no external library dependency). off-board components are flagged
`on_board no` ("Exclude from board"); board-main's connectionPoints are
grouped by id prefix (e.g. "J_ESP32") into real on-board connectors.

Usage:
    python generate_schematic.py [--yaml PATH] [--out PATH]
"""
from __future__ import annotations

import argparse
import math
import re
import uuid
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_YAML = REPO_ROOT / "papaya-wiring-layout.yaml"
DEFAULT_OUT = REPO_ROOT / "pathfinder" / "kicad" / "papaya-pcb" / "papaya-pcb.kicad_sch"

GRID = 2.54  # mm — a safe multiple of KiCad's underlying 1.27mm grid
PIN_PITCH = 2.54
PIN_LEN = 2.54
STUB_LEN = 2.54
BODY_HALF_WIDTH = 12.7
COL_SPACING = 40.64
ROW_SPACING = 45.72
COLS_PER_ROW = 6
ORIGIN = (25.4, 25.4)

REF_PREFIX_BY_TYPE = {
    "battery": "BT",
    "fuse": "F",
    "switch": "SW",
    "terminalBlock": "TB",
    "offBoard": "U",
}


# ----------------------------------------------------------------------------
# Tiny S-expression builder/printer
# ----------------------------------------------------------------------------
class Bare(str):
    """A value rendered without quotes (identifiers, numbers-as-tokens, yes/no)."""


def S(tag, *rest):
    return [Bare(tag), *rest]


def fmt_num(n):
    if isinstance(n, bool):
        raise TypeError("bool is not a number")
    if isinstance(n, int):
        return str(n)
    if float(n).is_integer():
        return str(int(n))
    s = f"{n:.4f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-") else "0"


def render_atom(a) -> str:
    if isinstance(a, Bare):
        return str(a)
    if isinstance(a, (int, float)):
        return fmt_num(a)
    if isinstance(a, str):
        return '"' + a.replace("\\", "\\\\").replace('"', '\\"') + '"'
    raise TypeError(f"unrenderable atom: {a!r}")


def render(node, depth=0) -> str:
    if not isinstance(node, list):
        return render_atom(node)
    if not node:
        return "()"
    tag, rest = node[0], node[1:]
    first_sub = next((i for i, c in enumerate(rest) if isinstance(c, list)), None)
    if first_sub is None:
        return "(" + " ".join([render_atom(tag)] + [render_atom(c) for c in rest]) + ")"
    head_atoms = rest[:first_sub]
    tail = rest[first_sub:]
    pad = "\t" * (depth + 1)
    closing = "\t" * depth
    opening = "(" + " ".join([render_atom(tag)] + [render_atom(a) for a in head_atoms])
    lines = [opening] + [f"{pad}{render(c, depth + 1)}" for c in tail]
    return "\n".join(lines) + f"\n{closing})"


def new_uuid() -> str:
    return str(uuid.uuid4())


def sanitize(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", s).upper()


# ----------------------------------------------------------------------------
# Union-find net computation
# ----------------------------------------------------------------------------
class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def build_nets(data):
    uf = UnionFind()
    member_bondgroup = {}
    for comp in data["components"]:
        for bg in comp.get("bondedGroups", []):
            pts = [(comp["id"], p) for p in bg["points"]]
            for p in pts:
                uf.find(p)
                member_bondgroup.setdefault(p, bg["id"])
            for i in range(1, len(pts)):
                uf.union(pts[0], pts[i])
    for conn in data["connections"]:
        a = (conn["from"]["component"], conn["from"]["point"])
        b = (conn["to"]["component"], conn["to"]["point"])
        uf.find(a)
        uf.find(b)
        uf.union(a, b)

    groups = {}
    for key in uf.parent:
        groups.setdefault(uf.find(key), []).append(key)

    nets = []
    for members in groups.values():
        if len(members) < 2:
            continue
        bg_ids = sorted({member_bondgroup[m] for m in members if m in member_bondgroup})
        if bg_ids:
            name = f"NET_{sanitize(bg_ids[0])}"
        else:
            rep = sorted(members)[0]
            name = f"NET_{sanitize(rep[0])}_{sanitize(rep[1])}"
        nets.append({"name": name, "members": members})
    return nets


# ----------------------------------------------------------------------------
# Reference designator assignment
# ----------------------------------------------------------------------------
def assign_ref(comp_id: str, comp_type: str, counters: dict) -> str:
    if re.fullmatch(r"[A-Za-z]+[0-9]+", comp_id):
        return comp_id.upper()
    if re.fullmatch(r"[A-Za-z]+", comp_id):
        return comp_id.upper() + "1"
    prefix = REF_PREFIX_BY_TYPE.get(comp_type, "U")
    counters[prefix] = counters.get(prefix, 0) + 1
    return f"{prefix}{counters[prefix]}"


def board_group_key(point_id: str):
    if "." in point_id:
        prefix, suffix = point_id.split(".", 1)
    else:
        prefix, suffix = point_id, "1"
    return prefix, suffix


# ----------------------------------------------------------------------------
# Build the list of symbols to place
# ----------------------------------------------------------------------------
def build_placements(data):
    placements = []
    pin_lookup = {}  # (yaml_component_id, yaml_point_id) -> (ref, pin_number)
    counters = {}

    board_comp = None
    for comp in data["components"]:
        if comp["componentType"] == "board":
            board_comp = comp
            continue
        ref = assign_ref(comp["id"], comp["componentType"], counters)
        pins = []
        for cp in comp.get("connectionPoints", []):
            label = cp.get("label") or cp["id"]
            pins.append((str(cp["id"]), str(label)))
            pin_lookup[(comp["id"], cp["id"])] = (ref, str(cp["id"]))
        placements.append(
            {
                "ref": ref,
                "value": comp.get("name") or comp["id"],
                "pins": pins,
                "on_board": False,
                "yaml_id": comp["id"],
            }
        )

    if board_comp is not None:
        groups_order = []
        groups = {}
        for cp in board_comp.get("connectionPoints", []):
            prefix, suffix = board_group_key(cp["id"])
            if prefix not in groups:
                groups[prefix] = []
                groups_order.append(prefix)
            groups[prefix].append((suffix, cp.get("label") or cp["id"], cp["id"]))

        j_counter = 0
        for prefix in groups_order:
            j_counter += 1
            ref = f"J{j_counter}"
            pins = [(suffix, str(label)) for suffix, label, _ in groups[prefix]]
            placements.append(
                {
                    "ref": ref,
                    "value": f"{prefix} ({len(pins)} pins)",
                    "pins": pins,
                    "on_board": True,
                    "yaml_id": prefix,
                }
            )
            for suffix, _, full_id in groups[prefix]:
                pin_lookup[(board_comp["id"], full_id)] = (ref, suffix)

    return placements, pin_lookup


# ----------------------------------------------------------------------------
# Symbol/pin geometry + S-expression generation
# ----------------------------------------------------------------------------
def col_positions(count):
    start = -(count - 1) * PIN_PITCH / 2
    return [start + i * PIN_PITCH for i in range(count)]


def pin_sexpr(number, name, local_x, local_y, rotation):
    return S(
        "pin",
        Bare("passive"),
        Bare("line"),
        S("at", local_x, local_y, rotation),
        S("length", PIN_LEN),
        S("name", name, S("effects", S("font", S("size", 1.27, 1.27)))),
        S("number", number, S("effects", S("font", S("size", 1.27, 1.27)))),
    )


def build_lib_symbol(placement):
    """Returns (lib_symbol_sexpr, {pin_number: (local_x, local_y, side)})."""
    lib_name = f"AUTO:{placement['ref']}"
    n = len(placement["pins"])
    left_n = (n + 1) // 2
    right_n = n - left_n
    left_pins = placement["pins"][:left_n]
    right_pins = placement["pins"][left_n:]
    left_ys = col_positions(left_n)
    right_ys = col_positions(right_n)

    max_col = max(left_n, right_n, 1)
    half_h = max(math.ceil((max_col * PIN_PITCH / 2 + PIN_PITCH / 2) / GRID) * GRID, GRID)
    half_w = BODY_HALF_WIDTH

    pin_geom = {}
    pin_sexprs = []
    for (num, name), ly in zip(left_pins, left_ys):
        local_x = -(half_w + PIN_LEN)
        pin_sexprs.append(pin_sexpr(num, name, local_x, ly, 0))
        pin_geom[num] = (local_x, ly, "left")
    for (num, name), ly in zip(right_pins, right_ys):
        local_x = half_w + PIN_LEN
        pin_sexprs.append(pin_sexpr(num, name, local_x, ly, 180))
        pin_geom[num] = (local_x, ly, "right")

    body = S(
        "symbol",
        f"{placement['ref']}_0_1",
        S(
            "rectangle",
            S("start", -half_w, half_h),
            S("end", half_w, -half_h),
            S("stroke", S("width", 0.254), S("type", Bare("default"))),
            S("fill", S("type", Bare("background"))),
        ),
    )
    pins_unit = S("symbol", f"{placement['ref']}_1_1", *pin_sexprs)

    lib_symbol = S(
        "symbol",
        lib_name,
        S("pin_numbers", S("hide", Bare("yes"))),
        S("pin_names", S("offset", 0.254)),
        S("exclude_from_sim", Bare("no")),
        S("in_bom", Bare("yes")),
        S("on_board", Bare("yes") if placement["on_board"] else Bare("no")),
        S("property", "Reference", placement["ref"][0], S("at", 0, half_h + 2.54, 0), S("effects", S("font", S("size", 1.27, 1.27)))),
        S("property", "Value", placement["value"], S("at", 0, -half_h - 2.54, 0), S("effects", S("font", S("size", 1.27, 1.27)))),
        S("property", "Footprint", "", S("at", 0, 0, 0), S("effects", S("font", S("size", 1.27, 1.27)), Bare("hide"))),
        S("property", "Datasheet", "", S("at", 0, 0, 0), S("effects", S("font", S("size", 1.27, 1.27)), Bare("hide"))),
        S("property", "YAML_Id", placement["yaml_id"], S("at", 0, 0, 0), S("effects", S("font", S("size", 1.27, 1.27)), Bare("hide"))),
        body,
        pins_unit,
        S("embedded_fonts", Bare("no")),
    )
    return lib_symbol, pin_geom, lib_name


def build_instance(placement, x, y, project_name, root_path, pin_geom):
    ref = placement["ref"]
    lib_name = f"AUTO:{ref}"
    inst_uuid = new_uuid()
    props = [
        S("property", "Reference", ref, S("at", x, y - 15.24, 0), S("effects", S("font", S("size", 1.27, 1.27)))),
        S("property", "Value", placement["value"], S("at", x, y + 15.24, 0), S("effects", S("font", S("size", 1.27, 1.27)))),
        S("property", "Footprint", "", S("at", x, y, 0), S("effects", S("font", S("size", 1.27, 1.27)), Bare("hide"))),
        S("property", "Datasheet", "", S("at", x, y, 0), S("effects", S("font", S("size", 1.27, 1.27)), Bare("hide"))),
    ]
    pins = [S("pin", num, S("uuid", new_uuid())) for num in pin_geom]
    instance = S(
        "symbol",
        S("lib_id", lib_name),
        S("at", x, y, 0),
        S("unit", 1),
        S("exclude_from_sim", Bare("no")),
        S("in_bom", Bare("yes")),
        S("on_board", Bare("yes") if placement["on_board"] else Bare("no")),
        S("dnp", Bare("no")),
        S("uuid", inst_uuid),
        *props,
        *pins,
        S(
            "instances",
            S(
                "project",
                project_name,
                S("path", root_path, S("reference", ref), S("unit", 1)),
            ),
        ),
    )
    world = {}
    for num, (local_x, local_y, side) in pin_geom.items():
        world[num] = (x + local_x, y - local_y, side)
    return instance, world


def build_wire_and_label(world_x, world_y, side, label_name):
    if side == "left":
        end_x = world_x - STUB_LEN
        justify = ["right", "bottom"]
    else:
        end_x = world_x + STUB_LEN
        justify = ["left", "bottom"]
    wire = S(
        "wire",
        S("pts", S("xy", world_x, world_y), S("xy", end_x, world_y)),
        S("stroke", S("width", 0), S("type", Bare("solid"))),
        S("uuid", new_uuid()),
    )
    label = S(
        "label",
        label_name,
        S("at", end_x, world_y, 0),
        S("effects", S("font", S("size", 1.27, 1.27)), S("justify", Bare(justify[0]), Bare(justify[1]))),
        S("uuid", new_uuid()),
    )
    return wire, label


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def read_existing_header(sch_path: Path):
    text = sch_path.read_text(encoding="utf-8")
    m = re.search(r"\(uuid ([0-9a-fA-F-]+)\)", text)
    root_uuid = m.group(1) if m else new_uuid()
    return root_uuid


def generate(yaml_path: Path, out_path: Path):
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    nets = build_nets(data)
    placements, pin_lookup = build_placements(data)

    root_uuid = read_existing_header(out_path)
    root_path = Bare(f"/{root_uuid}")
    project_name = out_path.parent.name

    lib_symbols = []
    instances = []
    wires_labels = []

    net_by_member = {}
    for net in nets:
        for m in net["members"]:
            net_by_member[m] = net["name"]

    for i, placement in enumerate(placements):
        col = i % COLS_PER_ROW
        row = i // COLS_PER_ROW
        x = ORIGIN[0] + col * COL_SPACING
        y = ORIGIN[1] + row * ROW_SPACING

        lib_symbol, pin_geom, _ = build_lib_symbol(placement)
        lib_symbols.append(lib_symbol)

        instance, world = build_instance(placement, x, y, project_name, root_path, pin_geom)
        instances.append(instance)

        for yaml_key, (ref, pin_num) in pin_lookup.items():
            if ref != placement["ref"]:
                continue
            net_name = net_by_member.get(yaml_key)
            if net_name is None:
                continue
            wx, wy, side = world[pin_num]
            wire, label = build_wire_and_label(wx, wy, side, net_name)
            wires_labels.append(wire)
            wires_labels.append(label)

    doc = S(
        "kicad_sch",
        S("version", Bare("20260306")),
        S("generator", "eeschema"),
        S("generator_version", "10.0"),
        S("uuid", Bare(root_uuid)),
        S("paper", "A4"),
        S("lib_symbols", *lib_symbols),
        *instances,
        *wires_labels,
        S("sheet_instances", S("path", "/", S("page", "1"))),
        S("embedded_fonts", Bare("no")),
    )

    out_path.write_text(render(doc) + "\n", encoding="utf-8")
    return len(placements), len(nets)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--yaml", type=Path, default=DEFAULT_YAML)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    n_symbols, n_nets = generate(args.yaml, args.out)
    print(f"Wrote {args.out} — {n_symbols} symbols, {n_nets} nets")


if __name__ == "__main__":
    main()
