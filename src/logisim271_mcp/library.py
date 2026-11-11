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


def ports(comp: Component) -> dict[str, Point] | None:
    """Absolute port locations, or None if geometry for this component is unknown."""
    facing = comp.attrs.get("facing", "east")
    x, y = comp.loc
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


def gate(kind: str, loc: Point, inputs: int = 2, label: str = "") -> Component:
    name = gate_name(kind)
    return Component("#Gates", name, loc, gate_attrs(name, inputs, label))


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
}

# Ports that may stay unconnected without changing behaviour (lint skips them).
OPTIONAL_PORTS = {
    "#Memory": {"Qn", "reset", "preset", "enable", "clear", "load", "count", "carry", "data"},
    "#Arithmetic": {"carry_in", "carry_out", "borrow_in", "borrow_out"},
    "#Plexers": set(),
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


def component_offsets(comp: Component) -> dict[str, Point] | None:
    """Port offsets (east-facing) for supported library components."""
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
    if comp.lib == "#Plexers" and n == "Multiplexer":
        return _mux_offsets(comp.attrs)
    if comp.lib == "#Arithmetic" and n in ("Adder", "Subtractor"):
        cin, cout = ("carry_in", "carry_out") if n == "Adder" else ("borrow_in", "borrow_out")
        return {"A": (-40, -10), "B": (-40, 10), "out": (0, 0), cin: (-20, -20), cout: (-20, 20)}
    return None


def optional_port(comp: Component, port: str) -> bool:
    return port in OPTIONAL_PORTS.get(comp.lib or "", set())


def component(kind: str, loc: Point, width: int = 1, select_bits: int = 2,
              label: str = "", trigger: str = "rising") -> Component:
    """A supported library component; ``kind`` is a key of COMPONENT_KINDS."""
    try:
        lib, name = COMPONENT_KINDS[kind.strip().lower()]
    except KeyError:
        raise ValueError(f"unknown component {kind!r}; use one of {sorted(COMPONENT_KINDS)}") from None
    attrs: dict[str, str] = {}
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
