"""Bit-width mismatch check (widths.width_issues)."""

import pytest

from logisim271_mcp import library as L
from logisim271_mcp import logic, sim, synth, widths
from logisim271_mcp.model import Component, Project
from test_components import _bench
from test_e2e import needs_logisim


def _two_pins(w_in, w_out, wire=True):
    proj = Project()
    c = proj.add_circuit("main")
    c.components.append(L.input_pin("A", (100, 100), w_in))
    c.components.append(L.output_pin("Q", (200, 100), w_out))
    if wire:
        c.add_wire((100, 100), (200, 100))
    return proj, c


def test_pin_mismatch_reported():
    proj, c = _two_pins(8, 5)
    (msg,) = widths.width_issues(c, proj)
    assert "5-bit: Q.tip" in msg and "8-bit: A.tip" in msg


def test_matching_and_unconnected_are_clean():
    proj, c = _two_pins(8, 8)
    assert widths.width_issues(c, proj) == []
    proj, c = _two_pins(8, 5, wire=False)
    assert widths.width_issues(c, proj) == []


def test_t_junction_joins_but_crossing_does_not():
    proj = Project()
    c = proj.add_circuit("main")
    c.components.append(L.input_pin("A", (100, 100), 8))
    c.components.append(L.output_pin("Q", (300, 100), 8))
    c.add_wire((100, 100), (300, 100))
    # vertical wire crossing mid-span: not connected, so no mismatch
    c.components.append(L.input_pin("B", (200, 50), 1))
    c.components.append(L.output_pin("R", (200, 150), 1))
    c.add_wire((200, 50), (200, 150))
    assert widths.width_issues(c, proj) == []
    # a wire END on the bus interior is a T-junction: now 1-bit R meets the 8-bit bus
    c.components.append(L.output_pin("S", (250, 150), 1))
    c.add_wire((250, 100), (250, 150))
    (msg,) = widths.width_issues(c, proj)
    assert "S.tip" in msg


def test_tunnels_join_nets():
    proj = Project()
    c = proj.add_circuit("main")
    c.components.append(L.input_pin("A", (100, 100), 4))
    c.components.append(L.tunnel("t", (100, 100), 4))
    c.components.append(L.tunnel("t", (300, 300), 4))
    c.components.append(L.output_pin("Q", (300, 300), 2))
    (msg,) = widths.width_issues(c, proj)
    assert "Q.tip" in msg


@pytest.mark.parametrize("kind,ins,outs,w,kw", [
    ("mux", ["in0", "in1", "in2", "in3", "select"], ["out"], {"in0": 4, "in1": 4, "in2": 4, "in3": 4, "select": 2, "out": 4}, {"width": 4, "select_bits": 2}),
    ("adder", ["A", "B", "carry_in"], ["out", "carry_out"], {"A": 8, "B": 8, "out": 8}, {"width": 8}),
    ("register", ["data", "clock", "enable"], ["out"], {"data": 6, "out": 6}, {"width": 6}),
    ("counter", ["clock"], ["out", "carry"], {"out": 3}, {"width": 3}),
    ("ram", ["addr", "din", "we", "clock"], ["data"], {"addr": 5, "din": 8, "data": 8}, {"addr_bits": 5, "width": 8}),
    ("decoder", ["select"], ["out0", "out3"], {"select": 2}, {"select_bits": 2}),
    ("splitter", ["combined"], ["split0", "split1"], {"combined": 8, "split0": 5, "split1": 3}, {"width": 8, "splits": [5, 3]}),
    ("bit_extender", ["in"], ["out"], {"in": 3, "out": 8}, {"in_width": 3, "width": 8}),
    ("dff", ["D", "clock"], ["Q"], {}, {}),
])
def test_correct_benches_are_clean(kind, ins, outs, w, kw):
    proj = _bench(kind, ins, outs, w, **kw)
    assert widths.width_issues(proj.circuit("main"), proj) == []


def test_wrong_bench_is_caught():
    proj = _bench("splitter", ["combined"], ["split0", "split1"],
                  {"combined": 8, "split0": 4, "split1": 3}, width=8, splits=[5, 3])
    (msg,) = widths.width_issues(proj.circuit("main"), proj)
    assert "split0" in msg


def test_defaults_when_width_attr_omitted():
    # GUI-made files omit default attributes: an Adder is then 8 bits wide
    proj = Project()
    c = proj.add_circuit("main")
    add = Component("#Arithmetic", "Adder", (300, 300), {})
    c.components.append(add)
    p = L.ports(add)
    c.components.append(L.input_pin("A", p["A"], 8))
    c.components.append(L.input_pin("B", p["B"], 4))
    (msg,) = widths.width_issues(c, proj)
    assert "4-bit: B.tip" in msg


def test_subcircuit_ports_use_pin_widths():
    proj = Project()
    sub = proj.add_circuit("sub")
    sub.components.append(L.input_pin("X", (100, 100), 4))
    sub.components.append(L.output_pin("Y", (200, 100), 4))
    main = proj.add_circuit("main")
    inst = Component(None, "sub", (300, 300))
    main.components.append(inst)
    p = L.ports(inst, proj)
    main.components.append(L.input_pin("A", p["X"], 3))
    (msg,) = widths.width_issues(main, proj)
    assert "3-bit: A.tip" in msg and "4-bit" in msg


@pytest.mark.parametrize("name", ["half_adder", "full_adder", "ripple2"])
def test_synthesized_circuits_are_clean(name):
    from test_e2e import CASES
    inputs, outputs = CASES[name]
    proj = Project()
    c = proj.add_circuit("main")
    logic.layout(c, inputs, outputs)
    assert widths.width_issues(c, proj) == []


@needs_logisim
def test_real_logisim_agrees():
    proj, _ = _two_pins(8, 5)
    # 2.7.1 headless prints a mismatched net as floating (x), not E
    assert sim.evaluate(proj, None, [{"A": 3}])[0]["Q"] == "xxxxx"
    proj, _ = _two_pins(8, 8)
    assert sim.evaluate(proj, None, [{"A": 3}])[0]["Q"] == 3
