"""stdio MCP server exposing Logisim 2.7.1 build + verify tools."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import library as L
from . import logic, sim, synth
from .model import Circuit, Component, Project, load, save

mcp = FastMCP(
    "logisim271",
    instructions=(
        "Build and verify digital circuits as Logisim 2.7.1 .circ files (the classic "
        "Carl Burch Logisim, not Evolution). Coordinates snap to a 10px grid. Gates face "
        "east; a gate's loc is its OUTPUT point and inputs sit to the left. Wires must be "
        "horizontal/vertical. A wire end touching another wire (even mid-span) connects; "
        "two wires crossing mid-span do not. "
        "Prefer build_logic / build_preset / build_from_truth_table, then confirm with "
        "truth_table or verify_truth_table. Flip-flops, registers, counters, muxes and adders: add_component (returns port "
        "coordinates). Clocked circuits: simulate_sequential (inputs held constant, or "
        "changed per cycle with sequence)."
    ),
)


def _path(p: str) -> Path:
    path = Path(p).expanduser()
    if not path.is_absolute():
        path = Path(os.environ.get("LOGISIM_WORKDIR") or os.getcwd()) / path
    if path.suffix.lower() != ".circ":
        raise ValueError("file must end with .circ")
    return path


def _open(p: str) -> tuple[Path, Project]:
    path = _path(p)
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist; call create_circuit_file first")
    return path, load(path)


def _circ(proj: Project, name: str | None, create: bool = False) -> Circuit:
    try:
        return proj.circuit(name)
    except LookupError:
        if create and name:
            return proj.add_circuit(name)
        raise


def _snap(v: int) -> int:
    if v % 10:
        raise ValueError(f"coordinate {v} is not on the 10px grid")
    return v


def _free_origin(c: Circuit) -> tuple[int, int]:
    if not c.components and not c.wires:
        return (100, 100)
    ys = [comp.loc[1] for comp in c.components] + [w.a[1] for w in c.wires] + [w.b[1] for w in c.wires]
    return (100, (max(ys) + 130) // 10 * 10)


def _comp_info(comp: Component, proj: Project | None = None) -> dict[str, Any]:
    d: dict[str, Any] = {"type": comp.name, "lib": comp.lib or "(subcircuit)", "loc": list(comp.loc)}
    if comp.label:
        d["label"] = comp.label
    extra = {k: v for k, v in comp.attrs.items() if k not in ("label", "labelloc", "tristate")}
    if extra:
        d["attrs"] = extra
    p = L.ports(comp, proj)
    if p:
        d["ports"] = {k: list(v) for k, v in p.items()}
    return d


def _on_interior(pt: tuple[int, int], w) -> bool:
    if w.a[0] == w.b[0] == pt[0]:
        return min(w.a[1], w.b[1]) < pt[1] < max(w.a[1], w.b[1])
    if w.a[1] == w.b[1] == pt[1]:
        return min(w.a[0], w.b[0]) < pt[0] < max(w.a[0], w.b[0])
    return False


def _lint(c: Circuit, proj: Project | None = None) -> list[str]:
    """Unconnected ports and dangling wire ends. In 2.7.1 a point touching a wire's
    middle IS connected (T-junction), and two wires crossing mid-span are NOT."""
    ends: dict[tuple[int, int], int] = {}
    for w in c.wires:
        for pt in (w.a, w.b):
            ends[pt] = ends.get(pt, 0) + 1

    def touches_wire(pt, skip=None) -> bool:
        return pt in ends or any(o is not skip and _on_interior(pt, o) for o in c.wires)
    port_pts: dict[tuple[int, int], int] = {}
    known = []
    for comp in c.components:
        p = L.ports(comp, proj)
        if p:
            known.append((comp, p))
            for pt in p.values():
                port_pts[pt] = port_pts.get(pt, 0) + 1
    issues = []
    for comp, p in known:
        for name, pt in p.items():
            if L.optional_port(comp, name):
                continue
            if not touches_wire(pt) and port_pts.get(pt, 0) < 2:
                who = comp.label or f"{comp.name}@{comp.loc}"
                issues.append(f"{who}.{name} at {pt} is unconnected")
    for w in c.wires:
        for pt in (w.a, w.b):
            if ends.get(pt, 0) == 1 and pt not in port_pts and \
                    not any(o is not w and _on_interior(pt, o) for o in c.wires):
                issues.append(f"wire end {pt} is dangling")
    return issues


# --------------------------------------------------------------------------- file / circuit

@mcp.tool()
def create_circuit_file(path: str, circuit: str = "main", overwrite: bool = False) -> dict:
    """Create an empty Logisim 2.7.1 project with one circuit."""
    p = _path(path)
    if p.exists() and not overwrite:
        raise FileExistsError(f"{p} exists; pass overwrite=true to replace it")
    p.parent.mkdir(parents=True, exist_ok=True)
    proj = Project(main=circuit)
    proj.add_circuit(circuit)
    save(proj, p)
    return {"path": str(p), "circuits": [circuit]}


@mcp.tool()
def list_circuits(path: str) -> dict:
    """List circuits in a .circ file with their input/output pins."""
    p, proj = _open(path)
    return {
        "path": str(p), "main": proj.main,
        "circuits": [{
            "name": c.name,
            "inputs": [{"label": x.label, "width": x.width()} for x in c.inputs()],
            "outputs": [{"label": x.label, "width": x.width()} for x in c.outputs()],
            "components": len(c.components), "wires": len(c.wires),
        } for c in proj.circuits],
    }


@mcp.tool()
def add_circuit(path: str, name: str) -> dict:
    """Add a new empty circuit (sub-circuit) to the project."""
    p, proj = _open(path)
    proj.add_circuit(name)
    save(proj, p)
    return {"circuits": [c.name for c in proj.circuits]}


@mcp.tool()
def delete_circuit(path: str, name: str) -> dict:
    """Delete a circuit. Refuses if it is main or used as a sub-circuit."""
    p, proj = _open(path)
    if name == proj.main:
        raise ValueError("cannot delete the main circuit; set_main_circuit first")
    for c in proj.circuits:
        if any(comp.lib is None and comp.name == name for comp in c.components):
            raise ValueError(f"{name!r} is used inside {c.name!r}")
    proj.circuits = [c for c in proj.circuits if c.name != name]
    save(proj, p)
    return {"circuits": [c.name for c in proj.circuits]}


@mcp.tool()
def set_main_circuit(path: str, name: str) -> dict:
    """Choose which circuit opens first in Logisim."""
    p, proj = _open(path)
    proj.circuit(name)
    proj.main = name
    save(proj, p)
    return {"main": name}


@mcp.tool()
def describe_circuit(path: str, circuit: str | None = None) -> dict:
    """Components (with absolute port coordinates), wires and connection warnings."""
    p, proj = _open(path)
    c = proj.circuit(circuit)
    return {
        "circuit": c.name,
        "components": [_comp_info(x, proj) for x in c.components],
        "wires": [[list(w.a), list(w.b)] for w in c.wires],
        "warnings": _lint(c, proj),
    }


# --------------------------------------------------------------------------- low level

@mcp.tool()
def add_pin(path: str, label: str, x: int, y: int, output: bool = False,
            width: int = 1, circuit: str | None = None) -> dict:
    """Add an input pin (faces east, connect at its loc) or output pin (faces west)."""
    p, proj = _open(path)
    c = proj.circuit(circuit)
    loc = (_snap(x), _snap(y))
    comp = L.output_pin(label, loc, width) if output else L.input_pin(label, loc, width)
    c.components.append(comp)
    save(proj, p)
    return _comp_info(comp)


@mcp.tool()
def add_gate(path: str, kind: str, x: int, y: int, inputs: int = 2,
             facing: str = "east", label: str = "", width: int = 1,
             circuit: str | None = None) -> dict:
    """Add AND/OR/NAND/NOR/XOR/XNOR (2-5 inputs), NOT or BUF.

    (x, y) is the gate's OUTPUT point. Returns absolute port coordinates to wire to.
    XOR/XNOR use parity semantics (odd number of 1s). width > 1 = bitwise on buses."""
    p, proj = _open(path)
    c = proj.circuit(circuit)
    comp = L.gate(kind, (_snap(x), _snap(y)), inputs=inputs, label=label, width=width)
    if facing != "east":
        comp.attrs["facing"] = facing
    c.components.append(comp)
    save(proj, p)
    return _comp_info(comp)


@mcp.tool()
def add_component(path: str, kind: str, x: int, y: int, width: int = 1, select_bits: int = 2,
                  label: str = "", trigger: str = "rising", addr_bits: int = 8,
                  splits: list[int] | None = None, in_width: int = 1,
                  circuit: str | None = None) -> dict:
    """Add a built-in library component (east-facing) and return its absolute ports.

    kind: dff | tff | jkff | srff (flip-flops: D/T or J,K / S,R, clock, Q, Qn, async
    reset / preset / enable), register (data, clock, clear, enable, out), counter
    (clock, count, load, data, clear, out, carry), mux (in0.., select, out;
    select_bits 1..4), adder (A, B, carry_in, out, carry_out), subtractor (A, B,
    borrow_in, out, borrow_out). width applies to register/counter/mux/adder/
    subtractor data. trigger (memory parts): rising | falling | high | low.
    ram: addr_bits x width RAM, separate ports (addr, data = read out, din, we = store
    on rising clock, clock, optional cs/oe/clear); load contents with ram_image in
    simulate_sequential or write_ram_image for the GUI. decoder: select -> out0..
    out(2**select_bits - 1). splitter: combined (width bits) <-> split0.. with group
    sizes ``splits`` LSB first, e.g. [5, 3]. bit_extender: in (in_width) -> out (width),
    zero-extended. Optional ports (Qn, reset, preset, enable, carry...) may stay
    unconnected; note an unconnected counter count input counts every cycle."""
    p, proj = _open(path)
    c = proj.circuit(circuit)
    comp = L.component(kind, (_snap(x), _snap(y)), width=width, select_bits=select_bits,
                       label=label, trigger=trigger, addr_bits=addr_bits, splits=splits,
                       in_width=in_width)
    c.components.append(comp)
    save(proj, p)
    return _comp_info(comp)


@mcp.tool()
def add_constant(path: str, value: int, x: int, y: int, width: int = 1,
                 circuit: str | None = None) -> dict:
    """Add a constant source (faces east; connect at its loc)."""
    p, proj = _open(path)
    c = proj.circuit(circuit)
    comp = L.constant(value, (_snap(x), _snap(y)), width)
    c.components.append(comp)
    save(proj, p)
    return _comp_info(comp)


@mcp.tool()
def add_subcircuit_instance(path: str, subcircuit: str, x: int, y: int, label: str = "",
                            circuit: str | None = None) -> dict:
    """Place an instance of another circuit of this project (east-facing, default
    appearance). Returns its ports keyed by the subcircuit's pin labels: input pins
    (facing east) on the west edge, output pins on the east edge, each top-to-bottom
    in the subcircuit's pin y order. Finish the subcircuit's pins before placing."""
    p, proj = _open(path)
    c = proj.circuit(circuit)
    proj.circuit(subcircuit)
    if subcircuit == c.name:
        raise ValueError("a circuit cannot contain itself")
    comp = Component(None, subcircuit, (_snap(x), _snap(y)), {"label": label} if label else {})
    c.components.append(comp)
    save(proj, p)
    return _comp_info(comp, proj)


@mcp.tool()
def add_wire(path: str, points: list[list[int]], circuit: str | None = None) -> dict:
    """Add a polyline wire through points [[x,y], ...]; each segment must be
    horizontal or vertical. An end landing on another wire joins it; crossings don't."""
    p, proj = _open(path)
    c = proj.circuit(circuit)
    pts = [(_snap(a), _snap(b)) for a, b in points]
    if len(pts) < 2:
        raise ValueError("need at least two points")
    for a, b in zip(pts, pts[1:]):
        c.add_wire(a, b)
    save(proj, p)
    return {"segments": len(pts) - 1, "warnings": _lint(c, proj)}


@mcp.tool()
def remove(path: str, label: str | None = None, x: int | None = None, y: int | None = None,
           wires_at: bool = False, circuit: str | None = None) -> dict:
    """Remove the component with ``label`` or at (x, y). With wires_at=true remove
    every wire having an endpoint at (x, y) instead."""
    p, proj = _open(path)
    c = proj.circuit(circuit)
    if wires_at:
        if x is None or y is None:
            raise ValueError("wires_at needs x and y")
        before = len(c.wires)
        c.wires = [w for w in c.wires if (x, y) not in (w.a, w.b)]
        removed = before - len(c.wires)
    else:
        if label:
            match = [comp for comp in c.components if comp.label == label]
        elif x is not None and y is not None:
            match = [comp for comp in c.components if comp.loc == (x, y)]
        else:
            raise ValueError("give label or x,y")
        if not match:
            raise LookupError("nothing matched")
        c.components = [comp for comp in c.components if comp not in match]
        removed = len(match)
    save(proj, p)
    return {"removed": removed}


# --------------------------------------------------------------------------- high level

def _build(path: str, circuit: str | None, inputs: list[str], outputs: dict[str, str],
           x: int | None, y: int | None, verify: bool) -> dict:
    p = _path(path)
    if p.exists():
        proj = load(p)
    else:
        proj = Project(main=circuit or "main")
        proj.add_circuit(circuit or "main")
    c = _circ(proj, circuit, create=True)
    origin = (_snap(x), _snap(y)) if x is not None and y is not None else _free_origin(c)
    info = logic.layout(c, inputs, outputs, origin=origin)
    save(proj, p)
    info["path"] = str(p)
    info["circuit"] = c.name
    if verify:
        info["verification"] = _verify_exprs(proj, c.name, outputs)
    return info


def _verify_exprs(proj: Project, circuit: str, outputs: dict[str, str]) -> dict:
    trees = {o: logic.parse(e) for o, e in outputs.items()}
    widths = sim.input_widths(proj, circuit)
    if sum(widths.values()) > 12:
        return {"skipped": "more than 12 input bits"}
    table = sim.truth_table(proj, circuit)
    bad = []
    for row in table:
        for o, t in trees.items():
            want = logic.eval_node(t, row["in"])
            if row["out"].get(o) != want:
                bad.append({"in": row["in"], "output": o, "expected": want, "got": row["out"].get(o)})
    return {"rows": len(table), "passed": not bad, "mismatches": bad[:20]}


@mcp.tool()
def build_logic(path: str, inputs: list[str], outputs: dict[str, str],
                circuit: str | None = None, x: int | None = None, y: int | None = None,
                verify: bool = True) -> dict:
    """Synthesize boolean expressions into gates, pins and wires (auto layout).

    outputs maps pin name -> expression. Syntax: NOT ~A !A A' ; AND A&B A*B A.B or 'A B';
    XOR A^B ; OR A|B A+B ; constants 0 1 ; parentheses. Creates the file/circuit if
    missing, places below existing content unless x,y given, then (verify=true) runs the
    full truth table in Logisim 2.7.1 and compares with the expressions."""
    return _build(path, circuit, inputs, outputs, x, y, verify)


@mcp.tool()
def build_preset(path: str, preset: str, circuit: str | None = None, bits: int | None = None,
                 select_bits: int | None = None, enable: bool = False,
                 x: int | None = None, y: int | None = None, verify: bool = True) -> dict:
    """Textbook circuits from gates: half_adder, full_adder, ripple_adder (bits 1..8,
    default 4), mux (select_bits 1..3, default 1; inputs D0.., S..), decoder (bits 1..3,
    default 2, optional EN), comparator (bits 1..4, default 2; outputs EQ GT LT).
    Circuit defaults to the preset name. Verified in Logisim after building."""
    if preset not in synth.PRESETS:
        raise ValueError(f"unknown preset; choose from {sorted(synth.PRESETS)}")
    kw: dict[str, Any] = {"enable": enable}
    if bits is not None:
        kw["bits"] = bits
    if select_bits is not None:
        kw["select_bits"] = select_bits
    ins, outs = synth.PRESETS[preset](**kw)
    res = _build(path, circuit or preset, ins, outs, x, y, verify)
    res["expressions"] = outs
    return res


@mcp.tool()
def build_from_truth_table(path: str, inputs: list[str], outputs: dict[str, list[int]],
                           dont_cares: dict[str, list[int]] | None = None,
                           circuit: str | None = None, x: int | None = None,
                           y: int | None = None, verify: bool = True) -> dict:
    """Minimize (Quine-McCluskey) and build. outputs maps name -> minterm indices,
    where the FIRST input is the most significant bit. Optional dont_cares likewise."""
    dont_cares = dont_cares or {}
    n = len(inputs)
    exprs = {}
    for o, ms in outputs.items():
        for m in list(ms) + list(dont_cares.get(o, [])):
            if not 0 <= m < (1 << n):
                raise ValueError(f"{o}: minterm {m} out of range for {n} inputs")
        exprs[o] = synth.sop(inputs, list(ms), list(dont_cares.get(o, [])))
    res = _build(path, circuit, inputs, exprs, x, y, False)
    res["expressions"] = exprs
    if verify:
        proj = load(_path(path))
        table = sim.truth_table(proj, res["circuit"])
        bad = []
        for row in table:
            m = 0
            for name in inputs:
                m = (m << 1) | row["in"][name]
            for o, ms in outputs.items():
                if m in dont_cares.get(o, []):
                    continue
                want = int(m in ms)
                if row["out"][o] != want:
                    bad.append({"minterm": m, "output": o, "expected": want, "got": row["out"][o]})
        res["verification"] = {"rows": len(table), "passed": not bad, "mismatches": bad[:20]}
    return res


# --------------------------------------------------------------------------- simulation

@mcp.tool()
def simulate(path: str, inputs: dict[str, int] | None = None,
             rows: list[dict[str, int]] | None = None, circuit: str | None = None) -> dict:
    """Run the circuit in Logisim 2.7.1 for one input assignment (inputs) or many (rows).
    Unlisted inputs are 0. Output values are ints; 'x' = floating, 'E' = error."""
    p, proj = _open(path)
    rs = rows if rows is not None else [inputs or {}]
    outs = sim.evaluate(proj, circuit, rs)
    return {"results": [{"in": r, "out": o} for r, o in zip(rs, outs)]}


@mcp.tool()
def truth_table(path: str, circuit: str | None = None, strict: bool = True) -> dict:
    """Full truth table (<=12 input bits) computed by Logisim 2.7.1.
    strict=true turns unconnected gate inputs into E so wiring bugs are visible."""
    p, proj = _open(path)
    table = sim.truth_table(proj, circuit, strict=strict)
    return {"rows": len(table), "table": table}


@mcp.tool()
def simulate_sequential(path: str, inputs: dict[str, int] | None = None, cycles: int = 8,
                        clock: str | None = None, circuit: str | None = None,
                        sequence: list[dict[str, int]] | None = None,
                        include_half_steps: bool = False,
                        ram_image: list[int] | None = None) -> dict:
    """Simulate a clocked (sequential) circuit in Logisim 2.7.1.
    The clock input pin (``clock``, auto-detected if labelled clk/clock) is driven by a
    free-running Clock; a Clock component already in the circuit also works. Other
    inputs are held at ``inputs`` (unlisted = 0). ``sequence`` (up to 16 steps) changes
    them per cycle: sequence[k] = inputs sampled at rising edge k+1, each step keeps
    earlier values it does not mention, and the last step stays in force.
    ram_image (words from address 0) is loaded into every RAM before the first edge.
    Returns power-on outputs and outputs after each rising edge (cycle 1..cycles)."""
    p, proj = _open(path)
    r = sim.run_clocked(proj, circuit, clock=clock, inputs=inputs, cycles=cycles,
                        sequence=sequence, ram_image=ram_image)
    if not include_half_steps:
        r.pop("half_steps")
    return r


@mcp.tool()
def write_ram_image(path: str, words: list[int]) -> dict:
    """Write a Logisim memory image file (v2.0 raw, words from address 0) that the GUI
    loads via right-click on a RAM -> Load Image... (or logisim -tty ... -load file)."""
    p = Path(path).expanduser().resolve()
    sim.write_ram_image(p, words)
    return {"path": str(p), "words": len(words)}


@mcp.tool()
def verify_truth_table(path: str, expected: list[dict[str, Any]] | None = None,
                       expressions: dict[str, str] | None = None,
                       circuit: str | None = None) -> dict:
    """Check the circuit against expected rows [{"in": {...}, "out": {...}}, ...]
    and/or reference expressions {output: expr} (checked on every input row)."""
    p, proj = _open(path)
    res: dict[str, Any] = {}
    if expressions:
        res["expressions"] = _verify_exprs(proj, proj.circuit(circuit).name, expressions)
    if expected:
        got = sim.evaluate(proj, circuit, [r["in"] for r in expected])
        bad = []
        for r, g in zip(expected, got):
            for k, v in r.get("out", {}).items():
                if g.get(k) != v:
                    bad.append({"in": r["in"], "output": k, "expected": v, "got": g.get(k)})
        res["rows"] = {"checked": len(expected), "passed": not bad, "mismatches": bad[:20]}
    if not res:
        raise ValueError("give expected rows or expressions")
    return res


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
