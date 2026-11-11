"""Boolean expressions -> shared gate netlist -> laid-out Logisim circuit.

Expression syntax (precedence high -> low):
    NOT : ~X  !X  X'  (postfix ')
    AND : X & Y   X * Y   X . Y   X Y (juxtaposition)
    XOR : X ^ Y
    OR  : X | Y   X + Y
    constants 0 / 1, parentheses, identifiers [A-Za-z_][A-Za-z0-9_]*
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import library as L
from .model import Circuit

# --------------------------------------------------------------------------- AST
# Node = ("in", name) | ("const", 0|1) | ("not", node) | (op, (node, ...)) op in and/or/xor


class ExprError(ValueError):
    pass


_TOKEN = re.compile(r"\s*(?:([A-Za-z_][A-Za-z0-9_]*)|([01])\b|(.))")


def _tokenize(s: str) -> list[str]:
    toks: list[str] = []
    pos = 0
    s = s.strip()
    while pos < len(s):
        m = _TOKEN.match(s, pos)
        if not m or m.end() == pos:
            break
        pos = m.end()
        tok = m.group(1) or m.group(2) or m.group(3)
        if tok and not tok.isspace():
            toks.append(tok)
    return toks


class _Parser:
    def __init__(self, text: str):
        self.toks = _tokenize(text)
        self.i = 0
        self.text = text

    def peek(self) -> str | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self) -> str:
        t = self.peek()
        if t is None:
            raise ExprError(f"unexpected end of expression: {self.text!r}")
        self.i += 1
        return t

    def parse(self):
        node = self.or_()
        if self.peek() is not None:
            raise ExprError(f"unexpected {self.peek()!r} in {self.text!r}")
        return node

    def or_(self):
        items = [self.xor_()]
        while self.peek() in ("|", "+"):
            self.take()
            items.append(self.xor_())
        return items[0] if len(items) == 1 else ("or", tuple(items))

    def xor_(self):
        items = [self.and_()]
        while self.peek() == "^":
            self.take()
            items.append(self.and_())
        return items[0] if len(items) == 1 else ("xor", tuple(items))

    def _starts_atom(self, t: str | None) -> bool:
        return t is not None and (t == "(" or t in "~!" or t in ("0", "1") or bool(re.match(r"[A-Za-z_]", t)))

    def and_(self):
        items = [self.unary()]
        while True:
            t = self.peek()
            if t in ("&", "*", ".", "·"):
                self.take()
                items.append(self.unary())
            elif self._starts_atom(t):
                items.append(self.unary())
            else:
                break
        return items[0] if len(items) == 1 else ("and", tuple(items))

    def unary(self):
        t = self.peek()
        if t in ("~", "!"):
            self.take()
            node = ("not", self.unary())
        else:
            node = self.atom()
        while self.peek() == "'":
            self.take()
            node = ("not", node)
        return node

    def atom(self):
        t = self.take()
        if t == "(":
            node = self.or_()
            if self.take() != ")":
                raise ExprError(f"missing ')' in {self.text!r}")
            return node
        if t in ("0", "1"):
            return ("const", int(t))
        if re.match(r"[A-Za-z_]", t):
            return ("in", t)
        raise ExprError(f"unexpected {t!r} in {self.text!r}")


def parse(text: str):
    return _Parser(text).parse()


def variables(node) -> set[str]:
    kind = node[0]
    if kind == "in":
        return {node[1]}
    if kind == "const":
        return set()
    if kind == "not":
        return variables(node[1])
    out: set[str] = set()
    for ch in node[1]:
        out |= variables(ch)
    return out


def eval_node(node, env: dict[str, int]) -> int:
    kind = node[0]
    if kind == "in":
        return env[node[1]] & 1
    if kind == "const":
        return node[1]
    if kind == "not":
        return 1 - eval_node(node[1], env)
    vals = [eval_node(c, env) for c in node[1]]
    if kind == "and":
        return int(all(vals))
    if kind == "or":
        return int(any(vals))
    r = 0
    for v in vals:
        r ^= v
    return r


# --------------------------------------------------------------------------- netlist

@dataclass
class Net:
    id: int
    kind: str          # "in" | "const" | gate name
    args: tuple[int, ...] = ()
    name: str = ""     # input name
    value: int = 0     # const value
    level: int = 0


class Netlist:
    def __init__(self) -> None:
        self.nets: list[Net] = []
        self._memo: dict[tuple, int] = {}

    def _mk(self, key: tuple, **kw) -> int:
        if key in self._memo:
            return self._memo[key]
        nid = len(self.nets)
        args = kw.get("args", ())
        level = 0 if not args else 1 + max(self.nets[a].level for a in args)
        self.nets.append(Net(id=nid, level=level, **kw))
        self._memo[key] = nid
        return nid

    def input(self, name: str) -> int:
        return self._mk(("in", name), kind="in", name=name)

    def const(self, v: int) -> int:
        return self._mk(("const", v), kind="const", value=v)

    def gate(self, kind: str, args: list[int]) -> int:
        if kind in ("AND Gate", "OR Gate", "XOR Gate", "NAND Gate", "NOR Gate", "XNOR Gate"):
            args = sorted(set(args)) if kind not in ("XOR Gate", "XNOR Gate") else sorted(args)
        key = (kind, tuple(args))
        return self._mk(key, kind=kind, args=tuple(args))

    def build(self, node) -> int:
        kind = node[0]
        if kind == "in":
            return self.input(node[1])
        if kind == "const":
            return self.const(node[1])
        if kind == "not":
            inner = node[1]
            if inner[0] == "not":
                return self.build(inner[1])
            return self.gate("NOT Gate", [self.build(inner)])
        op = {"and": "AND Gate", "or": "OR Gate", "xor": "XOR Gate"}[kind]
        flat = []
        for ch in node[1]:
            if ch[0] == kind:  # flatten nested same op
                flat.extend(ch[1])
            else:
                flat.append(ch)
        ids = [self.build(ch) for ch in flat]
        if kind != "xor":
            ids = sorted(set(ids))
        if len(ids) == 1:
            return ids[0]
        while len(ids) > L.MAX_INPUTS:
            chunks = [ids[i:i + L.MAX_INPUTS] for i in range(0, len(ids), L.MAX_INPUTS)]
            ids = [self.gate(op, c) if len(c) > 1 else c[0] for c in chunks]
        return self.gate(op, ids)


# --------------------------------------------------------------------------- layout

ROW_H = 60
TRACK = 10
X0 = 100
Y0 = 100


def layout(circ: Circuit, inputs: list[str], outputs: dict[str, str],
           origin: tuple[int, int] = (X0, Y0)) -> dict:
    """Synthesize ``outputs`` (name -> expression) into ``circ``.

    Every input pin / constant / gate / output pin gets a private row; gates
    sit in columns by logic level; each net owns one vertical track in the
    channel right after its source column, so no two nets ever touch.
    """
    trees = {}
    for oname, expr in outputs.items():
        try:
            trees[oname] = parse(expr)
        except ExprError as e:
            raise ExprError(f"output {oname}: {e}") from None
    used = set().union(*[variables(t) for t in trees.values()]) if trees else set()
    missing = used - set(inputs)
    if missing:
        raise ExprError(f"expressions use undeclared inputs {sorted(missing)}")
    taken = {c.label for c in circ.components if c.label}
    clash = (set(inputs) | set(outputs)) & taken
    if clash:
        raise ValueError(f"labels already used in circuit {circ.name!r}: {sorted(clash)}")

    nl = Netlist()
    for name in inputs:
        nl.input(name)
    out_nets = {o: nl.build(t) for o, t in trees.items()}

    # Drop nets not reachable from outputs (except declared inputs).
    live: set[int] = set()

    def mark(n: int) -> None:
        if n in live:
            return
        live.add(n)
        for a in nl.nets[n].args:
            mark(a)

    for n in out_nets.values():
        mark(n)
    for net in nl.nets:
        if net.kind == "in":
            live.add(net.id)

    nets = [n for n in nl.nets if n.id in live]
    max_level = max((n.level for n in nets), default=0)

    # Rows: sources first (inputs, consts), then gates by level, then outputs.
    row_of: dict[int, int] = {}
    r = 0
    for n in nets:
        if n.kind in ("in", "const"):
            row_of[n.id] = r; r += 1
    for lvl in range(1, max_level + 1):
        for n in nets:
            if n.level == lvl:
                row_of[n.id] = r; r += 1
    out_rows = {o: r + i for i, o in enumerate(outputs)}

    ox, oy = origin

    def row_y(rr: int) -> int:
        return oy + rr * ROW_H

    # Consumers per net: list of (y, kind, ref)
    sinks: dict[int, list[int]] = {n.id: [] for n in nets}
    port_y: dict[tuple[int, int], int] = {}
    for n in nets:
        if n.args:
            gname = n.kind
            cnt = len(n.args)
            dys = [0] if cnt == 1 else L._INPUT_DY[cnt]
            for i, a in enumerate(n.args):
                y = row_y(row_of[n.id]) + dys[i]
                port_y[(n.id, i)] = y
                sinks[a].append(n.id)
    for o, n in out_nets.items():
        sinks[n].append(-1)

    # Tracks per column channel: nets sourced in column c get tracks after it.
    by_col: dict[int, list[int]] = {}
    for n in nets:
        if sinks[n.id]:
            by_col.setdefault(n.level, []).append(n.id)

    # Column x positions (output x of gates / tip of pins in column 0).
    col_x: dict[int, int] = {0: ox}
    track_x: dict[int, int] = {}
    for c in range(0, max_level + 1):
        start = col_x[c] + 20
        for k, nid in enumerate(by_col.get(c, [])):
            track_x[nid] = start + k * TRACK
        chan_end = start + max(0, len(by_col.get(c, [])) - 1) * TRACK + 20
        nxt_axis = max((L.gate_axis(n.kind) for n in nets if n.level == c + 1), default=0)
        col_x[c + 1] = chan_end + nxt_axis
    out_x = col_x[max_level + 1] if max_level + 1 in col_x else col_x[max_level] + 60
    out_x = max(out_x, max(track_x.values(), default=ox) + 30)

    # Emit components.
    src_point: dict[int, tuple[int, int]] = {}
    for n in nets:
        y = row_y(row_of[n.id])
        if n.kind == "in":
            circ.components.append(L.input_pin(n.name, (ox, y)))
            src_point[n.id] = (ox, y)
        elif n.kind == "const":
            circ.components.append(L.constant(n.value, (ox, y)))
            src_point[n.id] = (ox, y)
        else:
            x = col_x[n.level]
            comp = L.gate(n.kind, (x, y), inputs=max(2, len(n.args)) if n.kind not in ("NOT Gate", "Buffer") else 1)
            circ.components.append(comp)
            src_point[n.id] = (x, y)
    for o, rr in out_rows.items():
        circ.components.append(L.output_pin(o, (out_x, row_y(rr))))

    # Wires.
    for n in nets:
        if not sinks[n.id]:
            continue
        tx = track_x[n.id]
        sx, sy = src_point[n.id]
        taps = {sy}
        circ.add_wire((sx, sy), (tx, sy))
        for consumer in set(sinks[n.id]):
            if consumer == -1:
                continue
            cn = nl.nets[consumer]
            gx = col_x[cn.level] - L.gate_axis(cn.kind)
            for i, a in enumerate(cn.args):
                if a == n.id:
                    py = port_y[(cn.id, i)]
                    circ.add_wire((tx, py), (gx, py))
                    taps.add(py)
        for o, on in out_nets.items():
            if on == n.id:
                py = row_y(out_rows[o])
                circ.add_wire((tx, py), (out_x, py))
                taps.add(py)
        ys = sorted(taps)
        for a, b in zip(ys, ys[1:]):  # split track at every tap
            circ.add_wire((tx, a), (tx, b))

    gates = sum(1 for n in nets if n.args)
    return {"gates": gates, "levels": max_level, "rows": r + len(outputs),
            "inputs": inputs, "outputs": list(outputs)}
