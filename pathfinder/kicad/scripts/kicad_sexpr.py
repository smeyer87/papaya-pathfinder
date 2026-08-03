"""Minimal S-expression tokenizer/parser for reading .kicad_sch files."""


def tokenize(s):
    toks = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c in "()":
            toks.append(c)
            i += 1
            continue
        if c == '"':
            j = i + 1
            buf = []
            while j < n and s[j] != '"':
                if s[j] == "\\" and j + 1 < n:
                    buf.append(s[j + 1])
                    j += 2
                else:
                    buf.append(s[j])
                    j += 1
            toks.append(("STR", "".join(buf)))
            i = j + 1
            continue
        j = i
        while j < n and s[j] not in " \t\r\n()":
            j += 1
        toks.append(("ATOM", s[i:j]))
        i = j
    return toks


def parse(toks):
    pos = [0]

    def parse_expr():
        t = toks[pos[0]]
        if t == "(":
            pos[0] += 1
            lst = []
            while toks[pos[0]] != ")":
                lst.append(parse_expr())
            pos[0] += 1
            return lst
        pos[0] += 1
        return t[1] if isinstance(t, tuple) else t

    return parse_expr()


def parse_file(path):
    text = open(path, encoding="utf-8").read()
    return parse(tokenize(text))


def find_all(node, tag):
    if isinstance(node, list) and node and node[0] == tag:
        yield node
    if isinstance(node, list):
        for c in node:
            yield from find_all(c, tag)


def extract_pin_names(sch_path):
    """Returns {ref: {pin_number: pin_name}} from a .kicad_sch's embedded lib_symbols."""
    tree = parse_file(sch_path)
    lib_symbols_node = next(find_all(tree, "lib_symbols"))
    result = {}
    for sym in lib_symbols_node[1:]:
        if not (isinstance(sym, list) and sym[0] == "symbol"):
            continue
        full_name = sym[1]
        ref = full_name.split(":", 1)[1] if ":" in full_name else full_name
        pins = {}
        for pin in find_all(sym, "pin"):
            name_val = None
            num_val = None
            for part in pin:
                if isinstance(part, list) and part and part[0] == "name":
                    name_val = part[1]
                if isinstance(part, list) and part and part[0] == "number":
                    num_val = part[1]
            if num_val is not None:
                pins[num_val] = name_val
        result[ref] = pins
    return result
