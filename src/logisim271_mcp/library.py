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
