"""Hand-drawn style schematics: components joined by real wires, checked.

Drawing a circuit the way a person would (wires, junction dots, rails)
instead of tunnel labels on every port is easy to get wrong in Logisim:

* a wire end, or any component port, lying on another wire (even mid-span)
  joins the two -- a T junction;
* two wires that only cross mid-span stay separate;
* two collinear wires that overlap are merged into one.

``Sheet`` records which net every wire and every port is meant to carry and
``check()`` recomputes connectivity with exactly those rules, so a short
(two nets touching), an open (one net in pieces) or a stray port touching
a wire is reported with coordinates before the file is ever opened.

Typical use::

    s = Sheet(proj, "FULL_ADDER")
    a = s.pin_in("A", (40, 100))
    x = s.gate("XOR", (220, 120), ["A", "B"], "P")
    s.wire("A", a, x["in0"])          # straight or polyline
    s.hvh("P", x["out"], y["in0"], 260)  # horizontal, vertical at x=260, horizontal
    s.check()
"""

from __future__ import annotations

from collections import defaultdict

from . import library as L
from .model import Component, Project

Point = tuple[int, int]


class SchematicError(ValueError):
    pass


class Sheet:
    def __init__(self, proj: Project, name: str):
        self.proj = proj
        self.c = proj.add_circuit(name)
        self.name = name
        self.wires: list[tuple[Point, Point, str]] = []
        self.decl: list[tuple[Point, str, str]] = []   # point, net, what
        self.tunnels: list[tuple[Point, str]] = []

    # ------------------------------------------------------------ components
    def add(self, comp: Component, nets: dict[str, str] | None = None) -> dict[str, Point]:
        """Place a component; ``nets`` maps port name -> intended net."""
        self.c.components.append(comp)
        offs = L.ports(comp, self.proj)
        if offs is None:
            raise SchematicError(f"{self.name}: no port geometry for {comp.name}")
        for port, net in (nets or {}).items():
            if port not in offs:
                raise SchematicError(f"{self.name}: {comp.name} has no port {port}")
            self.decl.append((offs[port], net, f"{comp.name}.{port}"))
        return offs

    def pin_in(self, label: str, pt: Point, width: int = 1, facing: str = "east",
               net: str | None = None) -> Point:
        comp = L.input_pin(label, pt, width)
        if facing != "east":
            comp.attrs["facing"] = facing
        return self.add(comp, {"tip": net or label})["tip"]

    def pin_out(self, label: str, pt: Point, width: int = 1, net: str | None = None) -> Point:
        return self.add(L.output_pin(label, pt, width), {"tip": net or label})["tip"]

    def const(self, value: int, pt: Point, net: str, width: int = 1,
              facing: str = "east") -> Point:
        return self.add(L.constant(value, pt, width, facing), {"tip": net})["tip"]

    def gate(self, kind: str, pt: Point, ins: list[str], out: str, width: int = 1,
             inputs: int | None = None) -> dict[str, Point]:
        n = inputs or len(ins)
        comp = L.gate(kind, pt, inputs=max(2, n), width=width)
        nets = {f"in{i}": s for i, s in enumerate(ins) if s is not None}
        nets["out"] = out
        return self.add(comp, nets)

    def part(self, kind: str, pt: Point, nets: dict[str, str], **kw) -> dict[str, Point]:
        return self.add(L.component(kind, pt, **kw), nets)

    def inst(self, name: str, pt: Point, nets: dict[str, str], label: str = "") -> dict[str, Point]:
        comp = Component(None, name, pt, {"label": label} if label else {})
        return self.add(comp, nets)

    def tunnel(self, label: str, pt: Point, width: int = 1, facing: str = "west") -> Point:
        t = L.tunnel(label, pt, width)
        t.attrs["facing"] = facing
        self.c.components.append(t)
        self.tunnels.append((pt, label))
        self.decl.append((pt, label, f"tunnel {label}"))
        return pt

    # ------------------------------------------------------------ wires
    def wire(self, net: str, *pts: Point) -> None:
        """Polyline through ``pts``; every segment must be horizontal or vertical."""
        clean = [pts[0]]
        for p in pts[1:]:
            if p != clean[-1]:
                clean.append(p)
        for a, b in zip(clean, clean[1:]):
            if a[0] != b[0] and a[1] != b[1]:
                raise SchematicError(f"{self.name}: diagonal wire {a}->{b} ({net})")
            if a[0] % 10 or a[1] % 10 or b[0] % 10 or b[1] % 10:
                raise SchematicError(f"{self.name}: off-grid wire {a}->{b} ({net})")
            self.c.add_wire(a, b)
            self.wires.append((a, b, net))

    def hv(self, net: str, a: Point, b: Point) -> None:
        self.wire(net, a, (b[0], a[1]), b)

    def vh(self, net: str, a: Point, b: Point) -> None:
        self.wire(net, a, (a[0], b[1]), b)

    def hvh(self, net: str, a: Point, b: Point, x: int) -> None:
        self.wire(net, a, (x, a[1]), (x, b[1]), b)

    def vhv(self, net: str, a: Point, b: Point, y: int) -> None:
        self.wire(net, a, (a[0], y), (b[0], y), b)

    def shift(self, dx: int, dy: int) -> None:
        """Move everything drawn so far (to make room on the left / top)."""
        mv = lambda p: (p[0] + dx, p[1] + dy)  # noqa: E731
        for comp in self.c.components:
            comp.loc = mv(comp.loc)
        for w in self.c.wires:
            w.a, w.b = mv(w.a), mv(w.b)
        self.wires = [(mv(a), mv(b), n) for a, b, n in self.wires]
        self.decl = [(mv(p), n, w) for p, n, w in self.decl]
        self.tunnels = [(mv(p), lab) for p, lab in self.tunnels]

    # ------------------------------------------------------------ check
    def check(self) -> None:
        errs = check_connectivity(self)
        if errs:
            raise SchematicError(f"{self.name}:\n  " + "\n  ".join(errs[:20]))


def _on(p: Point, a: Point, b: Point) -> bool:
    (x, y), (x0, y0), (x1, y1) = p, a, b
    if x0 == x1:
        return x == x0 and min(y0, y1) <= y <= max(y0, y1)
    return y == y0 and min(x0, x1) <= x <= max(x0, x1)


def check_connectivity(s: Sheet) -> list[str]:
    parent: dict = {}

    def find(k):
        parent.setdefault(k, k)
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def union(a, b):
        parent[find(a)] = find(b)

    # every port of every component (declared or not) is a connection point
    port_pts: dict[Point, list[str]] = defaultdict(list)
    for comp in s.c.components:
        offs = L.ports(comp, s.proj) or {}
        for name, pt in offs.items():
            port_pts[pt].append(f"{comp.name}{'[' + comp.attrs['label'] + ']' if comp.attrs.get('label') else ''}.{name}@{pt}")
    points = set(port_pts)
    for a, b, _ in s.wires:
        points.add(a)
        points.add(b)
    for i, (a, b, _) in enumerate(s.wires):
        find(("w", i))
        for p in points:
            if _on(p, a, b):
                union(("w", i), ("p", p))
    # collinear overlaps merge
    for i, (a, b, _) in enumerate(s.wires):
        for j in range(i + 1, len(s.wires)):
            c, d, _ = s.wires[j]
            if a[0] == b[0] == c[0] == d[0]:
                lo, hi = max(min(a[1], b[1]), min(c[1], d[1])), min(max(a[1], b[1]), max(c[1], d[1]))
            elif a[1] == b[1] == c[1] == d[1]:
                lo, hi = max(min(a[0], b[0]), min(c[0], d[0])), min(max(a[0], b[0]), max(c[0], d[0]))
            else:
                continue
            if lo < hi:
                union(("w", i), ("w", j))
    by_label = defaultdict(list)
    for pt, lab in s.tunnels:
        by_label[lab].append(pt)
    for pts in by_label.values():
        for p in pts[1:]:
            union(("p", p), ("p", pts[0]))

    group_nets: dict = defaultdict(set)
    net_groups: dict = defaultdict(set)
    where: dict = {}
    for i, (a, b, net) in enumerate(s.wires):
        g = find(("w", i))
        group_nets[g].add(net)
        net_groups[net].add(g)
        where.setdefault((g, net), f"wire {a}->{b}")
    declared = set()
    for pt, net, what in s.decl:
        g = find(("p", pt))
        group_nets[g].add(net)
        net_groups[net].add(g)
        where.setdefault((g, net), f"{what}@{pt}")
        declared.add(pt)
    errs = []
    for g, nets in group_nets.items():
        if len(nets) > 1:
            errs.append("short: " + ", ".join(f"{n} ({where.get((g, n), '?')})" for n in sorted(nets)))
    for net, gs in net_groups.items():
        if len(gs) > 1:
            parts = [where.get((g, net), "?") for g in gs]
            errs.append(f"open: net {net} in {len(gs)} pieces: " + "; ".join(parts[:6]))
    wire_pts = {p for a, b, _ in s.wires for p in points if _on(p, a, b)}
    for pt, names in port_pts.items():
        if pt in wire_pts and pt not in declared:
            g = find(("p", pt))
            errs.append(f"stray: {names} touches {sorted(group_nets.get(g, {'?'}))}")
    # a declared port that nothing reaches (no wire, no other port)
    for pt, net, what in s.decl:
        g = find(("p", pt))
        if pt not in wire_pts and len(port_pts.get(pt, [])) < 2 and len(net_groups[net]) == 1:
            others = [d for d in s.decl if d[1] == net and d[0] != pt]
            if others:
                errs.append(f"unconnected: {what} ({net})")
    return errs
