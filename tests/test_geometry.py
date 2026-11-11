"""Every gate kind x input count in library.py, wired by its computed port
locations and driven by constants, must compute the right function in real
Logisim 2.7.1 (with gateUndefined=error, so a missed port shows up as E)."""

import itertools
from functools import reduce

import pytest

from logisim271_mcp import library as L
from logisim271_mcp import model
from logisim271_mcp.runner import run_tty
from test_e2e import needs_logisim

FUNCS = {
    "AND": lambda b: all(b),
    "OR": lambda b: any(b),
    "NAND": lambda b: not all(b),
    "NOR": lambda b: not any(b),
    "XOR": lambda b: reduce(lambda x, y: x ^ y, b),
    "XNOR": lambda b: not reduce(lambda x, y: x ^ y, b),
    "NOT": lambda b: not b[0],
    "BUF": lambda b: b[0],
}


@needs_logisim
def test_gate_geometry(tmp_path):
    proj = model.Project()
    c = proj.add_circuit("main")
    expected = []
    y = 100
    for kind, f in FUNCS.items():
        counts = [1] if kind in ("NOT", "BUF") else range(2, L.MAX_INPUTS + 1)
        for n in counts:
            for facing in ("east", "west"):
                for bits in itertools.product([0, 1], repeat=n):
                    gx = 400
                    g = L.gate(kind, (gx, y), inputs=n)
                    if facing != "east":
                        g.attrs["facing"] = facing
                    c.components.append(g)
                    ports = L.ports(g)
                    sign = 1 if facing == "east" else -1
                    for i, b in enumerate(bits):
                        px, py = ports[f"in{i}"]
                        src = (px - 40 * sign, py)
                        c.components.append(L.constant(b, src, facing=facing))
                        c.add_wire(src, (px, py))
                    out = (gx + 30 * sign, y)
                    pin = L.output_pin(f"o{y}", out)
                    if facing == "west":
                        pin.attrs["facing"] = "east"
                    c.components.append(pin)
                    c.add_wire((gx, y), out)
                    expected.append(((kind, n, facing, bits), "1" if f(list(bits)) else "0"))
                    y += 120
    path = tmp_path / "g.circ"
    model.save(proj, path, gate_undefined="error")
    got = run_tty(path, timeout=90)
    assert len(got) == len(expected)
    bad = [(k, e, g) for (k, e), g in zip(expected, got) if e != g]
    assert not bad, bad[:10]
