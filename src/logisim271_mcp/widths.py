"""Bit-width mismatch check: group ports into nets via the wires and report
nets whose ports disagree on width (Logisim shows those as orange wires; the
headless 2.7.1 run just prints the net as floating x, which looks like a
missing wire).

Port widths follow the 2.7.1 sources (default widths included: Register,
Counter, Adder, Subtractor, RAM default to 8 bits, Bit Extender to 8 -> 16,
everything else to 1). Ports whose width is unknown -- components whose
geometry ``library.ports`` does not know, Probes, splitters without explicit
bit mapping -- are skipped, so the check can miss a mismatch but should not
invent one. The real Logisim run stays the final judge.
"""

from __future__ import annotations

from collections import defaultdict

from . import library as L
from .model import Circuit, Component, Point

_MEM_WIDE = {"Register", "Counter"}  # data/out use the width attribute, default 8


def _w(comp: Component, attr: str = "width", default: int = 1) -> int:
    try:
        return int(comp.attrs.get(attr, str(default)))
    except ValueError:
        return default


def _splitter_widths(comp: Component, port_names) -> dict[str, int | None]:
    incoming = _w(comp, "incoming", 2)
    fanout = _w(comp, "fanout", 2)
    res: dict[str, int | None] = {"combined": incoming}
    ends: list[int] | None = [0] * fanout
    for b in range(incoming):
        v = comp.attrs.get(f"bit{b}")
        if v is None:  # default distribution: leave the split ends unchecked
            ends = None
            break
        if v != "none":
            i = int(v)
            if 0 <= i < fanout:
                ends[i] += 1
    for name in port_names:
        if name.startswith("split"):
            res[name] = ends[int(name[5:])] if ends is not None else None
    return res


def port_widths(comp: Component, proj=None) -> dict[str, int | None] | None:
    """Port name -> bit width (None = unknown) for every port ``library.ports``
    knows, or None when the component's geometry is unknown."""
    pts = L.ports(comp, proj)
    if pts is None:
        return None
    n, lib = comp.name, comp.lib
    if lib is None:
        sub = proj.circuit(n)
        by_name = {p.label or f"pin@{p.loc}": p.width() for p in sub.components if p.is_pin()}
        return {k: by_name.get(k) for k in pts}
    if L.is_gate(comp) or (lib == "#Wiring" and n in ("Pin", "Constant", "Tunnel")):
        return {k: _w(comp) for k in pts}
    if lib == "#Wiring" and n == "Probe":
        return {k: None for k in pts}  # adapts to whatever it is attached to
    if lib == "#Wiring" and n == "Splitter":
        return _splitter_widths(comp, pts)
    if lib == "#Wiring" and n == "Bit Extender":
        return {"in": _w(comp, "in_width", 8), "out": _w(comp, "out_width", 16)}
    res: dict[str, int | None] = {k: 1 for k in pts}  # clocks, enables, carries, FFs
    if lib == "#Memory" and n in _MEM_WIDE:
        res["data"] = res["out"] = _w(comp, default=8)
    elif lib == "#Memory" and n == "RAM":
        res["addr"] = _w(comp, "addrWidth", 8)
        dw = _w(comp, "dataWidth", 8)
        for k in ("data", "din"):
            if k in res:
                res[k] = dw
    elif lib == "#Arithmetic":
        for k in ("A", "B", "out"):
            res[k] = _w(comp, default=8)
    elif lib == "#Plexers" and n == "Multiplexer":
        for k in pts:
            if k.startswith("in") or k == "out":
                res[k] = _w(comp)
        res["select"] = _w(comp, "select", 1)
    elif lib == "#Plexers" and n == "Decoder":
        res["select"] = _w(comp, "select", 1)
    return res


class _DSU:
    def __init__(self) -> None:
        self.parent: dict[Point, Point] = {}

    def find(self, p: Point) -> Point:
        self.parent.setdefault(p, p)
        while self.parent[p] != p:
            self.parent[p] = self.parent[self.parent[p]]
            p = self.parent[p]
        return p

    def union(self, a: Point, b: Point) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def nets(circ: Circuit, extra_points: set[Point]) -> _DSU:
    """Union wire endpoints, T-junctions (a wire end or port lying on another
    wire's interior) and tunnels with the same label. 2.7.1 does not join two
    wires that merely cross mid-span."""
    d = _DSU()
    points = set(extra_points)
    for w in circ.wires:
        d.union(w.a, w.b)
        points.update((w.a, w.b))
    horiz: dict[int, list] = defaultdict(list)
    vert: dict[int, list] = defaultdict(list)
    for w in circ.wires:
        if w.a[1] == w.b[1]:
            horiz[w.a[1]].append(w)
        else:
            vert[w.a[0]].append(w)
    for p in points:
        for w in horiz.get(p[1], ()):
            if min(w.a[0], w.b[0]) < p[0] < max(w.a[0], w.b[0]):
                d.union(p, w.a)
        for w in vert.get(p[0], ()):
            if min(w.a[1], w.b[1]) < p[1] < max(w.a[1], w.b[1]):
                d.union(p, w.a)
    tunnels: dict[str, Point] = {}
    for c in circ.components:
        if c.lib == "#Wiring" and c.name == "Tunnel" and c.label:
            if c.label in tunnels:
                d.union(c.loc, tunnels[c.label])
            else:
                tunnels[c.label] = c.loc
    return d


def width_issues(circ: Circuit, proj=None) -> list[str]:
    """One message per net whose known port widths disagree."""
    ports: list[tuple[str, Point, int]] = []
    for comp in circ.components:
        try:
            pw = port_widths(comp, proj)
        except (LookupError, ValueError):
            continue  # missing subcircuit, bad attribute: not this check's job
        if not pw:
            continue
        pts = L.ports(comp, proj)
        who = comp.label or f"{comp.name}@{comp.loc}"
        for name, w in pw.items():
            if w is not None:
                ports.append((f"{who}.{name}", pts[name], w))
    d = nets(circ, {pt for _, pt, _ in ports})
    by_net: dict[Point, list[tuple[str, Point, int]]] = defaultdict(list)
    for item in ports:
        by_net[d.find(item[1])].append(item)
    issues = []
    for items in by_net.values():
        widths = sorted({w for _, _, w in items})
        if len(widths) < 2:
            continue
        parts = []
        for w in widths:
            names = sorted(n for n, _, ww in items if ww == w)
            parts.append(f"{w}-bit: {', '.join(names)}")
        at = min(pt for _, pt, _ in items)
        issues.append(f"width mismatch on net at {at}: " + "; ".join(parts))
    return sorted(issues)
