"""End-to-end: synthesize circuits, simulate them in real Logisim 2.7.1,
and compare every row with Python evaluation of the expressions."""

import itertools
import tempfile
from pathlib import Path

import pytest

from logisim271_mcp import logic, model, sim, synth
from logisim271_mcp.runner import find_jar

try:
    find_jar()
    HAVE_LOGISIM = True
except FileNotFoundError:
    HAVE_LOGISIM = False

needs_logisim = pytest.mark.skipif(not HAVE_LOGISIM, reason="Logisim 2.7.1 not found")


def check(inputs, outputs, tmp):
    proj = model.Project()
    circ = proj.add_circuit("main")
    logic.layout(circ, inputs, outputs)
    path = Path(tmp) / "c.circ"
    model.save(proj, path)
    proj = model.load(path)  # round-trip through the file format
    table = sim.truth_table(proj)
    trees = {o: logic.parse(e) for o, e in outputs.items()}
    assert len(table) == 1 << len(inputs)
    for row in table:
        for o, t in trees.items():
            assert row["out"][o] == logic.eval_node(t, row["in"]), (o, row)


CASES = {
    "half_adder": synth.half_adder(),
    "full_adder": synth.full_adder(),
    "ripple2": synth.ripple_adder(2),
    "mux4": synth.mux(2),
    "decoder3": synth.decoder(3),
    "decoder2en": synth.decoder(2, enable=True),
    "comparator2": synth.comparator(2),
    "misc": (["A", "B", "C"], {
        "X": "A B' + C'",
        "Y": "~(A | B) ^ C",
        "Z": "A",
        "K": "1",
        "W": "A & B & C & A' | (A+B+C)",
    }),
    "wide_and": (list("ABCDEFG"), {"Y": "A&B&C&D&E&F&G", "Z": "A^B^C^D^E^F"}),
}


@needs_logisim
@pytest.mark.parametrize("name", list(CASES))
def test_synth(name, tmp_path):
    ins, outs = CASES[name]
    check(ins, outs, tmp_path)


@needs_logisim
def test_truth_table_synthesis(tmp_path):
    names = ["A", "B", "C", "D"]
    minterms = [0, 2, 5, 7, 8, 10, 13, 15]
    expr = synth.sop(names, minterms)
    check(names, {"F": expr}, tmp_path)
    tree = logic.parse(expr)
    for m in range(16):
        env = {n: (m >> (3 - i)) & 1 for i, n in enumerate(names)}
        assert logic.eval_node(tree, env) == (m in minterms)


def test_parse_errors():
    for bad in ["A &", "(A | B", "A $ B"]:
        with pytest.raises(logic.ExprError):
            logic.parse(bad)


def test_sop_unit():
    assert synth.sop(["A", "B"], [3]) == "A & B"
    assert synth.sop(["A", "B"], [0, 1, 2, 3]) == "1"
    assert synth.sop(["A", "B"], []) == "0"


@needs_logisim
def test_clocked_passthrough(tmp_path):
    from logisim271_mcp import library as L
    proj = model.Project()
    c = proj.add_circuit("main")
    c.components.append(L.input_pin("clk", (100, 100)))
    c.components.append(L.output_pin("Q", (200, 100)))
    c.components.append(L.input_pin("A", (100, 200)))
    c.components.append(L.output_pin("Y", (200, 200)))
    c.add_wire((100, 100), (200, 100))
    c.add_wire((100, 200), (200, 200))
    path = tmp_path / "c.circ"
    model.save(proj, path)
    r = sim.run_clocked(model.load(path), None, inputs={"A": 1}, cycles=3)
    assert r["clock"] == "clk"
    assert [s["out"]["Q"] for s in r["half_steps"]] == [0, 1, 0, 1, 0, 1, 0]
    assert all(s["out"]["Y"] == 1 for s in r["half_steps"])


def test_pin_names_unique():
    from logisim271_mcp import library as L
    pins = [L.input_pin("X", (0, 0)), L.input_pin("X", (0, 10)), L.input_pin("Y", (0, 20))]
    pins.append(model.Component("#Wiring", "Pin", (0, 30), {}))
    assert sim.pin_names(pins) == ["X#1", "X#2", "Y", "pin@0,30"]
