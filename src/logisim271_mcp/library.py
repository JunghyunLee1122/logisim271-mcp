"""Component geometry for Logisim 2.7.1, verified empirically against the
real 2.7.1 simulator (see tests/test_geometry.py).

All offsets are relative to the component ``loc`` for an east-facing
component. For gates ``loc`` is the output point.
"""

from __future__ import annotations

from .model import Component, Point

GATE_SIZE = 50
MAX_INPUTS = 5

# name -> (bonus width, negated output)
_GATES = {
    "AND Gate": (0, False),
    "OR Gate": (0, False),
    "NAND Gate": (0, True),
    "NOR Gate": (0, True),
    "XOR Gate": (10, False),
    "XNOR Gate": (10, True),
}
_SINGLE = {"NOT Gate": 30, "Buffer": 20}

GATE_ALIASES = {
    "AND": "AND Gate", "OR": "OR Gate", "NAND": "NAND Gate", "NOR": "NOR Gate",
    "XOR": "XOR Gate", "XNOR": "XNOR Gate", "NOT": "NOT Gate", "BUF": "Buffer",
    "BUFFER": "Buffer",
}

# Offsets for size=50, verified in Logisim 2.7.1.
_INPUT_DY = {
    2: [-20, 20],
    3: [-20, 0, 20],
    4: [-20, -10, 10, 20],
    5: [-20, -10, 0, 10, 20],
}


def gate_name(kind: str) -> str:
    k = kind.strip()
    if k in _GATES or k in _SINGLE:
        return k
    try:
        return GATE_ALIASES[k.upper()]
    except KeyError:
        raise ValueError(f"unknown gate {kind!r}; use one of {sorted(GATE_ALIASES)}") from None


def gate_axis(name: str) -> int:
    if name in _SINGLE:
        return _SINGLE[name]
    bonus, neg = _GATES[name]
    return GATE_SIZE + bonus + (10 if neg else 0)


def gate_attrs(name: str, inputs: int, label: str = "") -> dict[str, str]:
    attrs: dict[str, str] = {}
    if name not in _SINGLE:
        if not 2 <= inputs <= MAX_INPUTS:
            raise ValueError(f"{name}: inputs must be 2..{MAX_INPUTS}")
        attrs["size"] = str(GATE_SIZE)
        attrs["inputs"] = str(inputs)
        if name in ("XOR Gate", "XNOR Gate"):
            attrs["xor"] = "odd"  # 2.7.1 default is "exactly one"; textbook XOR is parity
    if label:
        attrs["label"] = label
    return attrs


def _rotate(dx: int, dy: int, facing: str) -> Point:
    if facing == "east":
        return (dx, dy)
    if facing == "west":
        return (-dx, -dy)
    if facing == "south":
        return (-dy, dx)
    if facing == "north":
        return (dy, -dx)
    raise ValueError(f"bad facing {facing!r}")


def gate_inputs_count(comp: Component) -> int:
    if comp.name in _SINGLE:
        return 1
    return int(comp.attrs.get("inputs", "5"))  # 2.7.1 default is 5


def is_gate(comp: Component) -> bool:
    return comp.lib == "#Gates" and (comp.name in _GATES or comp.name in _SINGLE)


def ports(comp: Component, proj=None) -> dict[str, Point] | None:
    """Absolute port locations, or None if geometry for this component is unknown.
    Subcircuit instances (lib None) need ``proj`` to look up the circuit's pins."""
    facing = comp.attrs.get("facing", "east")
    x, y = comp.loc
    if comp.lib is None:
        if proj is None or facing != "east":
            return None
        sub = proj.circuit(comp.name)
        if any(e.tag == "appear" for e in sub.extra):
            return None  # custom appearance: port layout is not the default one
        offs = subcircuit_offsets(sub)
        return {k: (x + dx, y + dy) for k, (dx, dy) in offs.items()}
    if is_gate(comp):
        if comp.attrs.get("size", "50") != "50" and comp.name not in _SINGLE:
            return None
        n = gate_inputs_count(comp)
        dys = [0] if n == 1 else _INPUT_DY.get(n)
        if dys is None:
            return None
        axis = gate_axis(comp.name)
        res = {"out": (x, y)}
        for i, dy in enumerate(dys):
            ox, oy = _rotate(-axis, dy, facing)
            res[f"in{i}"] = (x + ox, y + oy)
        return res
    if comp.lib == "#Wiring" and comp.name in ("Pin", "Constant", "Tunnel", "Probe"):
        return {"tip": (x, y)}
    offs = component_offsets(comp)
    if offs is not None:
        return {k: (x + dx, y + dy) for k, (dx, dy) in offs.items()}
    return None


def input_pin(label: str, loc: Point, width: int = 1) -> Component:
    attrs = {"tristate": "false"}
    if width != 1:
        attrs["width"] = str(width)
    attrs["label"] = label
    return Component("#Wiring", "Pin", loc, attrs)


def output_pin(label: str, loc: Point, width: int = 1) -> Component:
    attrs = {"facing": "west", "output": "true"}
    if width != 1:
        attrs["width"] = str(width)
    attrs["label"] = label
    attrs["labelloc"] = "east"
    return Component("#Wiring", "Pin", loc, attrs)


def constant(value: int, loc: Point, width: int = 1, facing: str = "east") -> Component:
    attrs: dict[str, str] = {}
    if facing != "east":
        attrs["facing"] = facing
    if width != 1:
        attrs["width"] = str(width)
    attrs["value"] = hex(value)
    return Component("#Wiring", "Constant", loc, attrs)


def gate(kind: str, loc: Point, inputs: int = 2, label: str = "", width: int = 1) -> Component:
    """``width`` > 1 makes a bitwise gate on multi-bit buses."""
    name = gate_name(kind)
    attrs = gate_attrs(name, inputs, label)
    if width != 1:
        if not 1 <= width <= 32:
            raise ValueError("width must be 1..32")
        attrs["width"] = str(width)
    return Component("#Gates", name, loc, attrs)


# --------------------------------------------------------------------------- library components
# Port offsets of non-gate 2.7.1 components for the default (east-facing)
# orientation, read from the 2.7.1 class files and checked in
# tests/test_components.py. Only east-facing, default-appearance placements
# are described; anything else returns None from ports().

_FF_ONE_INPUT = {"D Flip-Flop": "D", "T Flip-Flop": "T"}
_FF_TWO_INPUT = {"J-K Flip-Flop": ("J", "K"), "S-R Flip-Flop": ("S", "R")}
_FF_COMMON = {"Q": (0, 0), "Qn": (0, 20), "reset": (-10, 30), "preset": (-30, 30),
              "enable": (-20, 30)}

# component kind (tool-facing) -> (lib, Logisim name)
COMPONENT_KINDS = {
    "dff": ("#Memory", "D Flip-Flop"),
    "tff": ("#Memory", "T Flip-Flop"),
    "jkff": ("#Memory", "J-K Flip-Flop"),
    "srff": ("#Memory", "S-R Flip-Flop"),
    "register": ("#Memory", "Register"),
    "counter": ("#Memory", "Counter"),
    "mux": ("#Plexers", "Multiplexer"),
    "adder": ("#Arithmetic", "Adder"),
    "subtractor": ("#Arithmetic", "Subtractor"),
    "ram": ("#Memory", "RAM"),
    "decoder": ("#Plexers", "Decoder"),
    "splitter": ("#Wiring", "Splitter"),
    "bit_extender": ("#Wiring", "Bit Extender"),
}

# Ports that may stay unconnected without changing behaviour (lint skips them).
OPTIONAL_PORTS = {
    "#Memory": {"Qn", "reset", "preset", "enable", "clear", "load", "count", "carry", "data",
                "cs", "oe"},
    "#Arithmetic": {"carry_in", "carry_out", "borrow_in", "borrow_out"},
    "#Plexers": set(),
    "#Wiring": set(),
}


def _mux_offsets(attrs: dict[str, str]) -> dict[str, Point] | None:
    if attrs.get("selloc", "bl") != "bl":
        return None
    sel = int(attrs.get("select", "1"))
    n = 1 << sel
    if n == 2:
        res = {"in0": (-30, -10), "in1": (-30, 10)}
        sel_pt = (-20, 20)
    else:
        top = -(n // 2) * 10
        res = {f"in{i}": (-40, top + 10 * i) for i in range(n)}
        sel_pt = (-20, top + 10 * n)
    res["select"] = sel_pt
    if attrs.get("enable", "true") == "true":
        res["enable"] = (sel_pt[0] + 10, sel_pt[1])
    res["out"] = (0, 0)
    return res


def _splitter_offsets(attrs: dict[str, str]) -> dict[str, Point] | None:
    """SplitterParameters (2.7.1) for appear=left: the combined end is the
    origin, split end i sits 20 px towards the facing direction."""
    if attrs.get("appear", "left") != "left":
        return None
    f = int(attrs.get("fanout", "2"))
    facing = attrs.get("facing", "east")
    if facing == "east":
        ends = [(20, -10 * f + 10 * i) for i in range(f)]
    elif facing == "west":
        ends = [(-20, 10 + 10 * i) for i in range(f)]
    elif facing == "south":
        ends = [(10 * f - 10 * i, 20) for i in range(f)]
    elif facing == "north":
        ends = [(-10 - 10 * i, -20) for i in range(f)]
    else:
        return None
    res = {"combined": (0, 0)}
    res.update({f"split{i}": e for i, e in enumerate(ends)})
    return res


def component_offsets(comp: Component) -> dict[str, Point] | None:
    """Port offsets (east-facing) for supported library components.
    Splitters also support west / north / south facing."""
    if comp.lib == "#Wiring" and comp.name == "Splitter":
        return _splitter_offsets(comp.attrs)
    if comp.attrs.get("facing", "east") != "east":
        return None
    n = comp.name
    if comp.lib == "#Memory":
        if n in _FF_ONE_INPUT:
            return {_FF_ONE_INPUT[n]: (-40, 20), "clock": (-40, 0), **_FF_COMMON}
        if n in _FF_TWO_INPUT:
            a, b = _FF_TWO_INPUT[n]
            return {a: (-40, 0), b: (-40, 20), "clock": (-40, 10), **_FF_COMMON}
        if n == "Register":
            return {"out": (0, 0), "data": (-30, 0), "clock": (-20, 20), "clear": (-10, 20),
                    "enable": (-30, 10)}
        if n == "Counter":
            return {"out": (0, 0), "data": (-30, 0), "clock": (-20, 20), "clear": (-10, 20),
                    "load": (-30, -10), "count": (-30, 10), "carry": (0, 10)}
        if n == "RAM":
            # bus=separate: data = read port, din = write data, we = store on clock edge
            res = {"addr": (-140, 0), "data": (0, 0), "cs": (-90, 40), "oe": (-50, 40),
                   "clear": (-30, 40)}
            bus = comp.attrs.get("bus", "combined")
            if bus != "asynch":
                res["clock"] = (-70, 40)
            if bus == "separate":
                res["we"] = (-110, 40)
                res["din"] = (-140, 20)
            return res
    if comp.lib == "#Plexers" and n == "Multiplexer":
        return _mux_offsets(comp.attrs)
    if comp.lib == "#Plexers" and n == "Decoder":
        if comp.attrs.get("selloc", "bl") != "bl" or comp.attrs.get("enable", "true") != "false":
            return None
        k = 1 << int(comp.attrs.get("select", "1"))
        if k == 2:
            return None  # 1-bit select uses a different layout
        res = {f"out{i}": (20, -10 * k + 10 * i) for i in range(k)}
        res["select"] = (0, 0)
        return res
    if comp.lib == "#Wiring" and n == "Bit Extender":
        return {"out": (0, 0), "in": (-40, 0)}
    if comp.lib == "#Arithmetic" and n in ("Adder", "Subtractor"):
        cin, cout = ("carry_in", "carry_out") if n == "Adder" else ("borrow_in", "borrow_out")
        return {"A": (-40, -10), "B": (-40, 10), "out": (0, 0), cin: (-20, -20), cout: (-20, 20)}
    return None


def optional_port(comp: Component, port: str) -> bool:
    if comp.name == "Splitter" and port.startswith("split"):
        return True  # taking only some bit groups is normal
    if comp.name == "Decoder" and port.startswith("out"):
        return True
    return port in OPTIONAL_PORTS.get(comp.lib or "", set())


def component(kind: str, loc: Point, width: int = 1, select_bits: int = 2,
              label: str = "", trigger: str = "rising", addr_bits: int = 8,
              splits: list[int] | None = None, in_width: int = 1,
              facing: str = "east") -> Component:
    """A supported library component; ``kind`` is a key of COMPONENT_KINDS.

    ram: ``addr_bits`` x ``width`` RAM with separate load/store ports.
    decoder: ``select_bits`` -> 2**select_bits one-hot outputs.
    splitter: ``width``-bit combined end split into groups of ``splits`` bits
    (LSB first, e.g. [5, 3] = bits 0-4 and 5-7).
    bit_extender: ``in_width`` -> ``width`` bits, zero-extended."""
    try:
        lib, name = COMPONENT_KINDS[kind.strip().lower()]
    except KeyError:
        raise ValueError(f"unknown component {kind!r}; use one of {sorted(COMPONENT_KINDS)}") from None
    attrs: dict[str, str] = {}
    if name == "RAM":
        if not 2 <= addr_bits <= 24 or not 1 <= width <= 32:
            raise ValueError("ram: addr_bits 2..24, width 1..32")
        attrs.update({"addrWidth": str(addr_bits), "dataWidth": str(width), "bus": "separate"})
    if name == "Decoder":
        if not 2 <= select_bits <= 5:
            raise ValueError("decoder: select_bits 2..5")
        attrs.update({"select": str(select_bits), "enable": "false"})
    if name == "Splitter":
        splits = list(splits or [])
        if not splits or any(b < 1 for b in splits) or sum(splits) != width or len(splits) > 32:
            raise ValueError("splitter: splits must be positive group sizes summing to width")
        attrs.update({"fanout": str(len(splits)), "incoming": str(width), "appear": "left"})
        if facing != "east":
            if facing not in ("west", "north", "south"):
                raise ValueError("splitter facing: east, west, north or south")
            attrs["facing"] = facing
        b = 0
        for gi, n in enumerate(splits):
            for _ in range(n):
                attrs[f"bit{b}"] = str(gi)
                b += 1
    if name == "Bit Extender":
        if not 1 <= in_width <= 32 or not 1 <= width <= 32:
            raise ValueError("bit_extender: widths 1..32")
        attrs.update({"in_width": str(in_width), "out_width": str(width), "type": "zero"})
    if name in ("Register", "Counter", "Multiplexer", "Adder", "Subtractor"):
        if not 1 <= width <= 32:
            raise ValueError("width must be 1..32")
        attrs["width"] = str(width)
    if name == "Multiplexer":
        if not 1 <= select_bits <= 4:
            raise ValueError("select_bits must be 1..4")
        attrs["select"] = str(select_bits)
        attrs["enable"] = "false"
    if name == "Counter":
        attrs["max"] = hex((1 << width) - 1)
    if lib == "#Memory" and trigger != "rising":
        if trigger not in ("rising", "falling", "high", "low"):
            raise ValueError("trigger must be rising, falling, high or low")
        attrs["trigger"] = trigger
    if label:
        attrs["label"] = label
    return Component(lib, name, loc, attrs)


def tunnel(label: str, loc: Point, width: int = 1) -> Component:
    attrs = {"label": label}
    if width != 1:
        attrs["width"] = str(width)
    return Component("#Wiring", "Tunnel", loc, attrs)


# --------------------------------------------------------------------------- subcircuits
# Port layout of a subcircuit instance with Logisim 2.7.1's default appearance
# (circuit/appear/DefaultAppearance.java). A pin sits on the box edge opposite
# its facing (default input pin faces east -> west edge; our output pins face
# west -> east edge); each edge is sorted top-to-bottom / left-to-right.

_REV = {"east": "west", "west": "east", "north": "south", "south": "north"}


def _dim(max_this: int, max_others: int) -> int:
    if max_this < 3:
        return 30
    return 10 * max_this if max_others == 0 else 10 * max_this + 10


def _offset(n_facing: int, n_opposite: int, max_others: int) -> int:
    m = max(n_facing, n_opposite)
    if m <= 1:
        base = 15 if max_others == 0 else 10
    elif m == 2:
        base = 10
    else:
        base = 5 if max_others == 0 else 10
    return base + 10 * ((m - n_facing) // 2)


def subcircuit_offsets(circ) -> dict[str, Point]:
    """Pin label -> port offset from the instance's anchor (its loc)."""
    edge: dict[str, list[Component]] = {d: [] for d in ("north", "south", "east", "west")}
    for p in circ.components:
        if p.is_pin():
            edge[_REV[p.attrs.get("facing", "east")]].append(p)
    for d, lst in edge.items():
        if d in ("north", "south"):
            lst.sort(key=lambda c: (c.loc[0], c.loc[1]))
        else:
            lst.sort(key=lambda c: (c.loc[1], c.loc[0]))
    nN, nS, nE, nW = (len(edge[d]) for d in ("north", "south", "east", "west"))
    max_v, max_h = max(nN, nS), max(nE, nW)
    oN, oS = _offset(nN, nS, max_h), _offset(nS, nN, max_h)
    oE, oW = _offset(nE, nW, max_v), _offset(nW, nE, max_v)
    width, height = _dim(max_v, max_h), _dim(max_h, max_v)
    if nE:
        ax, ay = width, oE
    elif nN:
        ax, ay = oN, 0
    elif nW:
        ax, ay = 0, oW
    elif nS:
        ax, ay = oS, height
    else:
        ax, ay = 0, 0
    res: dict[str, Point] = {}

    def put(lst, x, y, dx, dy):
        for i, pin in enumerate(lst):
            name = pin.label or f"pin@{pin.loc}"
            if name in res:
                raise ValueError(f"subcircuit {circ.name!r}: duplicate pin label {name!r}")
            res[name] = (x + dx * i - ax, y + dy * i - ay)
    put(edge["west"], 0, oW, 0, 10)
    put(edge["east"], width, oE, 0, 10)
    put(edge["north"], oN, 0, 10, 0)
    put(edge["south"], oS, height, 10, 0)
    return res
