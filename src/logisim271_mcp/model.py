"""In-memory model of a Logisim 2.7.1 ``.circ`` project, plus parse/write.

Components reference libraries by *description* (``#Wiring``, ``#Gates`` …)
in memory; the numeric ``lib="N"`` index is only resolved when writing.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import quoteattr

Point = tuple[int, int]

STANDARD_LIBS = ["#Wiring", "#Gates", "#Plexers", "#Arithmetic", "#Memory", "#I/O", "#Base"]


def parse_point(s: str) -> Point:
    x, y = s.strip().strip("()").split(",")
    return (int(x), int(y))


def fmt_point(p: Point) -> str:
    return f"({p[0]},{p[1]})"


@dataclass
class Component:
    lib: str | None  # library desc like "#Gates"; None = subcircuit of this project
    name: str
    loc: Point
    attrs: dict[str, str] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.attrs.get("label", "")

    def is_pin(self) -> bool:
        return self.lib == "#Wiring" and self.name == "Pin"

    def is_output_pin(self) -> bool:
        return self.is_pin() and self.attrs.get("output") == "true"

    def is_input_pin(self) -> bool:
        return self.is_pin() and self.attrs.get("output") != "true"

    def width(self) -> int:
        return int(self.attrs.get("width", "1"))


@dataclass
class Wire:
    a: Point
    b: Point


@dataclass
class Circuit:
    name: str
    components: list[Component] = field(default_factory=list)
    wires: list[Wire] = field(default_factory=list)

    def inputs(self) -> list[Component]:
        return [c for c in self.components if c.is_input_pin()]

    def outputs(self) -> list[Component]:
        return [c for c in self.components if c.is_output_pin()]

    def find(self, label: str) -> Component:
        for c in self.components:
            if c.label == label:
                return c
        raise LookupError(f"no component labelled {label!r} in circuit {self.name!r}")

    def add_wire(self, a: Point, b: Point) -> None:
        if a == b:
            return
        if a[0] != b[0] and a[1] != b[1]:
            raise ValueError(f"wire {a}->{b} must be horizontal or vertical")
        self.wires.append(Wire(a, b))


@dataclass
class Project:
    circuits: list[Circuit] = field(default_factory=list)
    main: str = "main"
    libs: list[str] = field(default_factory=lambda: list(STANDARD_LIBS))

    def circuit(self, name: str | None = None) -> Circuit:
        name = name or self.main
        for c in self.circuits:
            if c.name == name:
                return c
        raise LookupError(f"no circuit {name!r}; have {[c.name for c in self.circuits]}")

    def add_circuit(self, name: str) -> Circuit:
        if any(c.name == name for c in self.circuits):
            raise ValueError(f"circuit {name!r} already exists")
        c = Circuit(name)
        self.circuits.append(c)
        return c


# --------------------------------------------------------------------------- parse

def load(path: str | Path) -> Project:
    root = ET.parse(str(path)).getroot()
    if root.tag != "project":
        raise ValueError("not a Logisim project file")
    idx_to_desc: dict[str, str] = {}
    libs: list[str] = []
    for lib in root.findall("lib"):
        idx_to_desc[lib.get("name", "")] = lib.get("desc", "")
        libs.append(lib.get("desc", ""))
    proj = Project(libs=libs or list(STANDARD_LIBS))
    main = root.find("main")
    for ce in root.findall("circuit"):
        circ = Circuit(ce.get("name", ""))
        for we in ce.findall("wire"):
            circ.wires.append(Wire(parse_point(we.get("from")), parse_point(we.get("to"))))
        for comp in ce.findall("comp"):
            lib_idx = comp.get("lib")
            attrs = {a.get("name"): a.get("val", "") for a in comp.findall("a")}
            circ.components.append(Component(
                lib=idx_to_desc.get(lib_idx) if lib_idx is not None else None,
                name=comp.get("name", ""), loc=parse_point(comp.get("loc")), attrs=attrs))
        proj.circuits.append(circ)
    proj.main = main.get("name") if main is not None else (proj.circuits[0].name if proj.circuits else "main")
    return proj


# --------------------------------------------------------------------------- write

_HEADER_TAIL = """  <options>
    <a name="gateUndefined" val="{undef}"/>
    <a name="simlimit" val="1000"/>
    <a name="simrand" val="0"/>
  </options>
  <mappings>
    <tool lib="{base}" map="Button2" name="Menu Tool"/>
    <tool lib="{base}" map="Button3" name="Menu Tool"/>
    <tool lib="{base}" map="Ctrl Button1" name="Menu Tool"/>
  </mappings>
  <toolbar>
    <tool lib="{base}" name="Poke Tool"/>
    <tool lib="{base}" name="Edit Tool"/>
    <sep/>
    <tool lib="{wiring}" name="Pin">
      <a name="tristate" val="false"/>
    </tool>
    <tool lib="{wiring}" name="Pin">
      <a name="facing" val="west"/>
      <a name="output" val="true"/>
      <a name="labelloc" val="east"/>
    </tool>
    <tool lib="{gates}" name="NOT Gate"/>
    <tool lib="{gates}" name="AND Gate"/>
    <tool lib="{gates}" name="OR Gate"/>
  </toolbar>
"""


def to_xml(proj: Project, gate_undefined: str = "ignore") -> str:
    libs = list(proj.libs)
    for c in proj.circuits:
        for comp in c.components:
            if comp.lib and comp.lib not in libs:
                libs.append(comp.lib)
    for need in ("#Wiring", "#Gates", "#Base"):
        if need not in libs:
            libs.append(need)
    idx = {d: str(i) for i, d in enumerate(libs)}
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
           '<project source="2.7.1" version="1.0">',
           "This file is intended to be loaded by Logisim (http://www.cburch.com/logisim/).",
           ]
    for d in libs:
        out.append(f'  <lib desc={quoteattr(d)} name="{idx[d]}"/>')
    out.append(f"  <main name={quoteattr(proj.main)}/>")
    out.append(_HEADER_TAIL.format(undef=gate_undefined, base=idx["#Base"],
                                   wiring=idx["#Wiring"], gates=idx["#Gates"]).rstrip("\n"))
    for c in proj.circuits:
        out.append(f"  <circuit name={quoteattr(c.name)}>")
        out.append(f'    <a name="circuit" val={quoteattr(c.name)}/>')
        for w in c.wires:
            out.append(f'    <wire from="{fmt_point(w.a)}" to="{fmt_point(w.b)}"/>')
        for comp in c.components:
            lib_attr = f' lib="{idx[comp.lib]}"' if comp.lib else ""
            head = f'    <comp{lib_attr} loc="{fmt_point(comp.loc)}" name={quoteattr(comp.name)}'
            if not comp.attrs:
                out.append(head + "/>")
                continue
            out.append(head + ">")
            for k, v in comp.attrs.items():
                out.append(f"      <a name={quoteattr(k)} val={quoteattr(v)}/>")
            out.append("    </comp>")
        out.append("  </circuit>")
    out.append("</project>")
    return "\n".join(out) + "\n"


def save(proj: Project, path: str | Path, gate_undefined: str = "ignore") -> None:
    Path(path).write_text(to_xml(proj, gate_undefined), encoding="utf-8")


