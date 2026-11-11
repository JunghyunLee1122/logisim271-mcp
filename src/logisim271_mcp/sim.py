"""Combinational simulation via Logisim 2.7.1 ``-tty table``.

2.7.1's tty mode only settles the circuit once with whatever the input pins
hold (pin values are not saved in the file, so they are all 0). To evaluate
many input rows in a single JVM run we build a throw-away project whose
main circuit contains one translated copy of the target circuit per row,
with every input pin replaced by a Constant of the row's value. tty prints
output pins sorted by (y, x), so the copies are stacked vertically.
"""

from __future__ import annotations

import copy
import itertools
import tempfile
from pathlib import Path

from .model import Circuit, Component, Project, Wire, save
from .runner import run_tty, run_tty_lines

TEST_CIRCUIT = "__logisim271_mcp_test__"
MAX_ROWS = 4096


def _bbox(c: Circuit) -> tuple[int, int, int, int]:
    xs, ys = [], []
    for comp in c.components:
        xs.append(comp.loc[0]); ys.append(comp.loc[1])
    for w in c.wires:
        xs += [w.a[0], w.b[0]]; ys += [w.a[1], w.b[1]]
    if not xs:
        return (0, 0, 0, 0)
    return (min(xs), min(ys), max(xs), max(ys))


def _sorted_outputs(c: Circuit) -> list[Component]:
    return sorted(c.outputs(), key=lambda p: (p.loc[1], p.loc[0]))


def pin_names(pins: list[Component]) -> list[str]:
    """Unique names: the label, or label#k when labels repeat, or pin@x,y if unlabelled."""
    base = [p.label or f"pin@{p.loc[0]},{p.loc[1]}" for p in pins]
    seen: dict[str, int] = {}
    out = []
    for b in base:
        if base.count(b) > 1:
            seen[b] = seen.get(b, 0) + 1
            out.append(f"{b}#{seen[b]}")
        else:
            out.append(b)
    return out


def _parse_value(s: str) -> int | str:
    s = s.strip()
    if s and all(ch in "01" for ch in s):
        return int(s, 2)
    return s  # 'x' (floating), 'E' (error) or mixed like '1x0E'


def evaluate(proj: Project, circuit: str | None, rows: list[dict[str, int]],
             timeout: float = 60.0, strict: bool = True) -> list[dict[str, int | str]]:
    """Evaluate ``circuit`` for each input assignment; returns output dicts.

    ``strict`` makes unconnected gate inputs produce E instead of being
    silently ignored (Logisim's default), so wiring mistakes surface.
    """
    if not rows:
        return []
    if len(rows) > MAX_ROWS:
        raise ValueError(f"too many rows ({len(rows)} > {MAX_ROWS})")
    target = proj.circuit(circuit)
    inputs = target.inputs()
    names_in = dict(zip(pin_names(inputs), inputs))
    outs = _sorted_outputs(target)
    if not outs:
        raise ValueError(f"circuit {target.name!r} has no output pins")
    for r in rows:
        unknown = set(r) - set(names_in)
        if unknown:
            raise ValueError(f"unknown input(s) {sorted(unknown)}; inputs are {sorted(names_in)}")

    x0, y0, x1, y1 = _bbox(target)
    pitch = (y1 - y0) + 100
    pitch = (pitch + 9) // 10 * 10

    test = Project(circuits=[copy.deepcopy(c) for c in proj.circuits if c.name != TEST_CIRCUIT],
                   main=TEST_CIRCUIT, libs=list(proj.libs))
    tc = test.add_circuit(TEST_CIRCUIT)
    for ri, row in enumerate(rows):
        dy = ri * pitch - y0 + 50
        dx = -x0 + 50
        for comp in target.components:
            loc = (comp.loc[0] + dx, comp.loc[1] + dy)
            if comp.is_input_pin():
                name = next(n for n, p in names_in.items() if p is comp)
                val = int(row.get(name, 0))
                w = comp.width()
                if val < 0 or val >= (1 << w):
                    raise ValueError(f"value {val} does not fit {w}-bit input {name!r}")
                attrs = {"width": str(w), "value": hex(val)}
                if "facing" in comp.attrs:
                    attrs["facing"] = comp.attrs["facing"]
                tc.components.append(Component("#Wiring", "Constant", loc, attrs))
            else:
                nc = copy.deepcopy(comp)
                nc.loc = loc
                tc.components.append(nc)
        for w in target.wires:
            tc.wires.append(Wire((w.a[0] + dx, w.a[1] + dy), (w.b[0] + dx, w.b[1] + dy)))

    with tempfile.TemporaryDirectory(prefix="logisim271_") as td:
        path = Path(td) / "test.circ"
        save(test, path, gate_undefined="error" if strict else "ignore")
        values = run_tty(path, timeout=timeout)
    expected_cols = len(rows) * len(outs)
    if len(values) != expected_cols:
        raise RuntimeError(f"expected {expected_cols} output values, Logisim printed {len(values)}")
    names_out = pin_names(outs)
    res = []
    for ri in range(len(rows)):
        chunk = values[ri * len(outs):(ri + 1) * len(outs)]
        res.append({n: _parse_value(v) for n, v in zip(names_out, chunk)})
    return res


CLOCK_NAMES = ("clk", "clock", "ck", "cp")
MAX_CYCLES = 200


def run_clocked(proj: Project, circuit: str | None, clock: str | None = None,
                inputs: dict[str, int] | None = None, cycles: int = 8,
                timeout: float = 60.0, strict: bool = False) -> dict:
    """Simulate a sequential circuit with a free-running clock.

    The clock input pin (``clock``, or one labelled clk/clock) is replaced by a
    Logisim Clock component; other inputs become Constants (fixed for the whole
    run). A second, identical Clock wired to an extra output pin at the top makes
    tty print a line on every half period, so line i is the state after i clock
    edges (line 0 = power-on, odd lines = after a rising edge).
    """
    if not 1 <= cycles <= MAX_CYCLES:
        raise ValueError(f"cycles must be 1..{MAX_CYCLES}")
    inputs = dict(inputs or {})
    target = proj.circuit(circuit)
    ins = target.inputs()
    names_in = dict(zip(pin_names(ins), ins))
    if clock is None:
        cands = [n for n in names_in if n.split("#")[0].strip().lower() in CLOCK_NAMES]
        has_clock_comp = any(c.name == "Clock" for c in target.components)
        if len(cands) == 1:
            clock = cands[0]
        elif not cands and not has_clock_comp:
            raise ValueError(f"no clock pin found; pass clock=<one of {sorted(names_in)}>")
        elif len(cands) > 1:
            raise ValueError(f"several clock-like pins {cands}; pass clock=")
    if clock is not None and clock not in names_in:
        raise ValueError(f"unknown clock pin {clock!r}; inputs are {sorted(names_in)}")
    unknown = set(inputs) - set(names_in) - {clock}
    if unknown:
        raise ValueError(f"unknown input(s) {sorted(unknown)}; inputs are {sorted(names_in)}")
    outs = _sorted_outputs(target)
    if not outs:
        raise ValueError(f"circuit {target.name!r} has no output pins")

    x0, y0, _, _ = _bbox(target)
    dx, dy = -x0 + 150, -y0 + 150
    test = Project(circuits=[copy.deepcopy(c) for c in proj.circuits if c.name != TEST_CIRCUIT],
                   main=TEST_CIRCUIT, libs=list(proj.libs))
    tc = test.add_circuit(TEST_CIRCUIT)
    clock_pin = names_in.get(clock) if clock else None
    for comp in target.components:
        loc = (comp.loc[0] + dx, comp.loc[1] + dy)
        if comp is clock_pin:
            attrs = {k: v for k, v in comp.attrs.items() if k in ("facing", "label")}
            tc.components.append(Component("#Wiring", "Clock", loc, attrs))
        elif comp.is_input_pin():
            name = next(n for n, p in names_in.items() if p is comp)
            val, w = int(inputs.get(name, 0)), comp.width()
            if val < 0 or val >= (1 << w):
                raise ValueError(f"value {val} does not fit {w}-bit input {name!r}")
            attrs = {"width": str(w), "value": hex(val)}
            if "facing" in comp.attrs:
                attrs["facing"] = comp.attrs["facing"]
            tc.components.append(Component("#Wiring", "Constant", loc, attrs))
        else:
            nc = copy.deepcopy(comp)
            nc.loc = loc
            tc.components.append(nc)
    for w in target.wires:
        tc.wires.append(Wire((w.a[0] + dx, w.a[1] + dy), (w.b[0] + dx, w.b[1] + dy)))
    # observer: Clock -> output pin, top-most so it is tty column 0
    tc.components.append(Component("#Wiring", "Clock", (50, 50), {}))
    tc.components.append(Component("#Wiring", "Pin", (100, 50),
                                   {"facing": "west", "output": "true", "label": "__clk__"}))
    tc.wires.append(Wire((50, 50), (100, 50)))

    n = 2 * cycles + 1
    with tempfile.TemporaryDirectory(prefix="logisim271_") as td:
        path = Path(td) / "test.circ"
        save(test, path, gate_undefined="error" if strict else "ignore")
        lines = run_tty_lines(path, n, timeout=timeout)
    names_out = pin_names(outs)
    steps = []
    for i, vals in enumerate(lines):
        if len(vals) != len(outs) + 1:
            raise RuntimeError(f"line {i}: expected {len(outs) + 1} values, got {len(vals)}")
        steps.append({"step": i, "clk": _parse_value(vals[0]),
                      "out": {nm: _parse_value(v) for nm, v in zip(names_out, vals[1:])}})
    for i, s in enumerate(steps):
        if s["clk"] != i % 2:
            raise RuntimeError(f"clock observer out of phase at line {i}: {s['clk']}")
    return {
        "clock": clock,
        "inputs": inputs,
        "initial": steps[0]["out"],
        "after_rising_edge": [{"cycle": k + 1, "out": steps[2 * k + 1]["out"]}
                              for k in range(cycles)],
        "half_steps": steps,
    }


def input_widths(proj: Project, circuit: str | None) -> dict[str, int]:
    ins = proj.circuit(circuit).inputs()
    return {n: p.width() for n, p in zip(pin_names(ins), ins)}


def all_rows(widths: dict[str, int]) -> list[dict[str, int]]:
    total = sum(widths.values())
    if total > 12:
        raise ValueError(f"{total} input bits -> too many rows; pass explicit rows instead")
    names = list(widths)
    ranges = [range(1 << widths[n]) for n in names]
    return [dict(zip(names, combo)) for combo in itertools.product(*ranges)]


def truth_table(proj: Project, circuit: str | None = None, timeout: float = 60.0,
                strict: bool = True):
    widths = input_widths(proj, circuit)
    rows = all_rows(widths) if widths else [{}]
    outs = evaluate(proj, circuit, rows, timeout=timeout, strict=strict)
    return [{"in": r, "out": o} for r, o in zip(rows, outs)]
