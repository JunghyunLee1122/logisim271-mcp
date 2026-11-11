"""Library components placed by library.component() and wired at the port
locations library.ports() reports must behave correctly in real Logisim 2.7.1."""

import itertools

import pytest

from logisim271_mcp import library as L
from logisim271_mcp.model import Project
from logisim271_mcp.sim import evaluate, run_clocked
from test_e2e import needs_logisim

LOC = (300, 300)


def _bench(kind, inputs, outputs, widths=None, **kw):
    """Component at LOC; an input pin on each port in ``inputs`` and an output
    pin on each port in ``outputs`` (pin label = port name)."""
    widths = widths or {}
    proj = Project()
    c = proj.add_circuit("main")
    comp = L.component(kind, LOC, **kw)
    c.components.append(comp)
    ports = L.ports(comp)
    assert ports is not None
    for name in inputs:
        c.components.append(L.input_pin(name, ports[name], widths.get(name, 1)))
    for name in outputs:
        c.components.append(L.output_pin(name, ports[name], widths.get(name, 1)))
    return proj


@needs_logisim
@pytest.mark.parametrize("sel", [1, 2, 3, 4])
def test_mux(sel):
    n = 1 << sel
    ins = [f"in{i}" for i in range(n)]
    proj = _bench("mux", ins + ["select"], ["out"], {"select": sel}, select_bits=sel)
    rows = [{"select": s, f"in{i}": 1} for s in range(n) for i in range(n)]
    got = evaluate(proj, None, rows)
    for r, g in zip(rows, got):
        hot = next(k for k in r if k.startswith("in"))
        assert g["out"] == int(hot == f"in{r['select']}"), (r, g)


@needs_logisim
@pytest.mark.parametrize("kind,sign", [("adder", 1), ("subtractor", -1)])
def test_arith(kind, sign):
    cin, cout = ("carry_in", "carry_out") if kind == "adder" else ("borrow_in", "borrow_out")
    proj = _bench(kind, ["A", "B", cin], ["out", cout], {"A": 2, "B": 2, "out": 2}, width=2)
    rows = [{"A": a, "B": b, cin: c} for a, b, c in itertools.product(range(4), range(4), (0, 1))]
    for r, g in zip(rows, evaluate(proj, None, rows)):
        if sign > 0:
            t = r["A"] + r["B"] + r[cin]
            assert (g["out"], g[cout]) == (t & 3, t >> 2), (r, g)
        else:
            t = r["A"] - r["B"] - r[cin]
            assert (g["out"], g[cout]) == (t & 3, int(t < 0)), (r, g)


def _clocked(proj, inputs, cycles=2):
    r = run_clocked(proj, None, clock="clock", inputs=inputs, cycles=cycles)
    return r["initial"], [s["out"] for s in r["after_rising_edge"]]


@needs_logisim
def test_dff_and_async():
    proj = _bench("dff", ["D", "clock", "reset", "preset"], ["Q", "Qn"])
    init, after = _clocked(proj, {"D": 1})
    assert init == {"Q": 0, "Qn": 1} and after[0] == {"Q": 1, "Qn": 0}
    _, after = _clocked(proj, {"D": 1, "reset": 1})
    assert after[0]["Q"] == 0
    init, _ = _clocked(proj, {"preset": 1})
    assert init["Q"] == 1


@needs_logisim
def test_dff_enable():
    proj = _bench("dff", ["D", "clock", "enable"], ["Q"])
    assert _clocked(proj, {"D": 1, "enable": 0})[1][0]["Q"] == 0
    assert _clocked(proj, {"D": 1, "enable": 1})[1][0]["Q"] == 1


@needs_logisim
def test_tff():
    proj = _bench("tff", ["T", "clock"], ["Q"])
    _, after = _clocked(proj, {"T": 1}, cycles=3)
    assert [a["Q"] for a in after] == [1, 0, 1]


@needs_logisim
@pytest.mark.parametrize("kind,a,b", [("jkff", "J", "K"), ("srff", "S", "R")])
def test_two_input_ff(kind, a, b):
    proj = _bench(kind, [a, b, "clock"], ["Q", "Qn"])
    assert _clocked(proj, {a: 1})[1][0]["Q"] == 1
    if kind == "jkff":
        _, after = _clocked(proj, {a: 1, b: 1}, cycles=3)
        assert [x["Q"] for x in after] == [1, 0, 1]


@needs_logisim
def test_register():
    proj = _bench("register", ["data", "clock", "clear", "enable"], ["out"],
                  {"data": 4, "out": 4}, width=4)
    assert _clocked(proj, {"data": 9, "enable": 1})[1][0]["out"] == 9
    assert _clocked(proj, {"data": 9, "enable": 0})[1][0]["out"] == 0
    assert _clocked(proj, {"data": 9, "enable": 1, "clear": 1})[1][0]["out"] == 0


@needs_logisim
def test_counter():
    proj = _bench("counter", ["clock", "count", "load", "data", "clear"], ["out", "carry"],
                  {"data": 2, "out": 2}, width=2)
    _, after = _clocked(proj, {"count": 1}, cycles=4)
    assert [a["out"] for a in after] == [1, 2, 3, 0]
    assert [a["carry"] for a in after] == [0, 0, 1, 0]
    assert _clocked(proj, {"load": 1, "data": 2})[1][0]["out"] == 2
    assert _clocked(proj, {"count": 0})[1][0]["out"] == 0


@needs_logisim
def test_sequence_drives_inputs_per_cycle():
    proj = _bench("dff", ["D", "clock"], ["Q"])
    r = run_clocked(proj, None, clock="clock", cycles=6,
                    sequence=[{"D": 1}, {"D": 0}, {"D": 1}, {}, {"D": 0}])
    assert [e["out"]["Q"] for e in r["after_rising_edge"]] == [1, 0, 1, 1, 0, 0]
    assert [e["in"]["D"] for e in r["after_rising_edge"]] == [1, 0, 1, 1, 0, 0]


@needs_logisim
def test_sequence_multibit_with_held_input():
    proj = _bench("register", ["data", "clock", "enable"], ["out"], {"data": 4, "out": 4}, width=4)
    r = run_clocked(proj, None, clock="clock", inputs={"enable": 1}, cycles=4,
                    sequence=[{"data": 9}, {"data": 5}, {"enable": 0, "data": 3}])
    assert [e["out"]["out"] for e in r["after_rising_edge"]] == [9, 5, 5, 5]


def test_sequence_rejects_clock_and_unknown():
    proj = _bench("dff", ["D", "clock"], ["Q"])
    with pytest.raises(ValueError):
        run_clocked(proj, None, clock="clock", sequence=[{"clock": 1}])
    with pytest.raises(ValueError):
        run_clocked(proj, None, clock="clock", sequence=[{"nope": 1}])


@needs_logisim
def test_evaluate_splits_large_batches(monkeypatch):
    from logisim271_mcp import sim
    monkeypatch.setattr(sim, "ELEMENT_BUDGET", 40)   # forces several Logisim runs
    proj = _bench("adder", ["A", "B", "carry_in"], ["out", "carry_out"],
                  {"A": 3, "B": 3, "out": 3}, width=3)
    rows = [{"A": a, "B": b, "carry_in": c} for a in range(8) for b in range(8) for c in (0, 1)]
    for r, g in zip(rows, evaluate(proj, None, rows)):
        t = r["A"] + r["B"] + r["carry_in"]
        assert (g["out"], g["carry_out"]) == (t & 7, t >> 3)


def test_lint_skips_optional_ports(tmp_path):
    from logisim271_mcp import server
    proj = _bench("dff", ["D", "clock"], ["Q"])
    issues = server._lint(proj.circuit("main"))
    assert issues == []
    c = proj.circuit("main")
    c.components = [x for x in c.components if x.label != "D"]
    assert any(".D at" in i for i in server._lint(c))
