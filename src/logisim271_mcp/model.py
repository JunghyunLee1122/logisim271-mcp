"""In-memory model of a Logisim 2.7.1 ``.circ`` project, plus parse/write.

Components reference libraries by *description* (``#Wiring``, ``#Gates`` …)
in memory; the numeric ``lib="N"`` index is only resolved when writing.
"""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

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
    # circuit-level <a> attributes other than "circuit" (which mirrors name),
    # e.g. clabel / circuitnamedbox; kept so a load/save round-trip loses nothing
    attrs: dict[str, str] = field(default_factory=dict)
    # child elements this model does not understand (e.g. <appear>), verbatim
    extra: list[ET.Element] = field(default_factory=list)

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
    # Elements preserved from a loaded file, written back verbatim. Any
    # ``lib`` attribute inside them holds the library *desc*, not the index.
    lib_tools: dict[str, list[ET.Element]] = field(default_factory=dict)  # <lib> children
    head: dict[str, ET.Element] = field(default_factory=dict)  # options/mappings/toolbar
    extra: list[ET.Element] = field(default_factory=list)  # other unknown top-level elements

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

HEAD_TAGS = ("options", "mappings", "toolbar")


def _attr_value(a: ET.Element) -> str:
    # Logisim writes long / multi-line values (ROM "contents", multi-line text)
    # as element text instead of a val="" attribute.
    v = a.get("val")
    return v if v is not None else (a.text or "")


def _attrs(parent: ET.Element) -> dict[str, str]:
    return {a.get("name", ""): _attr_value(a) for a in parent.findall("a")}


def _relib(el: ET.Element, mapping: dict[str, str]) -> ET.Element:
    """Deep copy of ``el`` with every ``lib`` attribute translated via ``mapping``
    (index -> desc on load, desc -> index on write). Unknown keys are kept."""
    el = copy.deepcopy(el)
    for e in el.iter():
        lib = e.get("lib")
        if lib is not None and lib in mapping:
            e.set("lib", mapping[lib])
    return el


def load(path: str | Path) -> Project:
    root = ET.parse(str(path)).getroot()
    if root.tag != "project":
        raise ValueError("not a Logisim project file")
    idx_to_desc: dict[str, str] = {}
    libs: list[str] = []
    lib_tools: dict[str, list[ET.Element]] = {}
    for lib in root.findall("lib"):
        desc = lib.get("desc", "")
        idx_to_desc[lib.get("name", "")] = desc
        libs.append(desc)
        if len(lib):
            lib_tools[desc] = [copy.deepcopy(t) for t in lib]
    proj = Project(libs=libs or list(STANDARD_LIBS), lib_tools=lib_tools)
    main = root.find("main")
    for el in root:
        if el.tag in HEAD_TAGS:
            proj.head[el.tag] = _relib(el, idx_to_desc)
        elif el.tag not in ("lib", "main", "circuit"):
            proj.extra.append(_relib(el, idx_to_desc))
    for ce in root.findall("circuit"):
        circ = Circuit(ce.get("name", ""))
        for el in ce:
            if el.tag == "a":
                if el.get("name") != "circuit":
                    circ.attrs[el.get("name", "")] = _attr_value(el)
            elif el.tag == "wire":
                circ.wires.append(Wire(parse_point(el.get("from")), parse_point(el.get("to"))))
            elif el.tag == "comp":
                lib_idx = el.get("lib")
                circ.components.append(Component(
                    lib=idx_to_desc.get(lib_idx) if lib_idx is not None else None,
                    name=el.get("name", ""), loc=parse_point(el.get("loc")), attrs=_attrs(el)))
            else:
                circ.extra.append(_relib(el, idx_to_desc))
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


def _fmt_a(k: str, v: str, indent: str) -> str:
    if "\n" in v:  # multi-line values (ROM contents, text) go in element text
        return f"{indent}<a name={quoteattr(k)}>{escape(v)}</a>"
    return f"{indent}<a name={quoteattr(k)} val={quoteattr(v)}/>"


def _fmt_el(el: ET.Element, idx: dict[str, str], level: int) -> str:
    el = _relib(el, idx)
    el.tail = None
    ET.indent(el, space="  ", level=level)
    return "  " * level + ET.tostring(el, encoding="unicode").rstrip()


def _referenced_libs(el: ET.Element) -> list[str]:
    return [e.get("lib") for e in el.iter() if e.get("lib") is not None]


def to_xml(proj: Project, gate_undefined: str | None = None) -> str:
    """``gate_undefined`` overrides the file's option; ``None`` keeps the value
    preserved from a loaded file (or "ignore" for a new project)."""
    libs = list(proj.libs)
    wanted = [comp.lib for c in proj.circuits for comp in c.components if comp.lib]
    for el in [*proj.head.values(), *proj.extra, *(e for c in proj.circuits for e in c.extra)]:
        wanted += _referenced_libs(el)
    wanted += ["#Wiring", "#Gates", "#Base"]
    for d in wanted:
        if d not in libs:
            libs.append(d)
    idx = {d: str(i) for i, d in enumerate(libs)}
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
           '<project source="2.7.1" version="1.0">',
           "This file is intended to be loaded by Logisim (http://www.cburch.com/logisim/).",
           ]
    for d in libs:
        tools = proj.lib_tools.get(d)
        if not tools:
            out.append(f'  <lib desc={quoteattr(d)} name="{idx[d]}"/>')
            continue
        out.append(f'  <lib desc={quoteattr(d)} name="{idx[d]}">')
        out.extend(_fmt_el(t, idx, 2) for t in tools)
        out.append("  </lib>")
    out.append(f"  <main name={quoteattr(proj.main)}/>")
    if proj.head:
        head = dict(proj.head)
        if gate_undefined is not None:
            opts = copy.deepcopy(head.get("options", ET.Element("options")))
            a = next((a for a in opts.findall("a") if a.get("name") == "gateUndefined"), None)
            if a is None:
                a = ET.SubElement(opts, "a", name="gateUndefined")
            a.set("val", gate_undefined)
            head["options"] = opts
        out.extend(_fmt_el(head[t], idx, 1) for t in HEAD_TAGS if t in head)
    else:
        out.append(_HEADER_TAIL.format(undef=gate_undefined or "ignore", base=idx["#Base"],
                                       wiring=idx["#Wiring"], gates=idx["#Gates"]).rstrip("\n"))
    out.extend(_fmt_el(e, idx, 1) for e in proj.extra)
    for c in proj.circuits:
        out.append(f"  <circuit name={quoteattr(c.name)}>")
        out.append(f'    <a name="circuit" val={quoteattr(c.name)}/>')
        for k, v in c.attrs.items():
            out.append(_fmt_a(k, v, "    "))
        out.extend(_fmt_el(e, idx, 2) for e in c.extra)
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
                out.append(_fmt_a(k, v, "      "))
            out.append("    </comp>")
        out.append("  </circuit>")
    out.append("</project>")
    return "\n".join(out) + "\n"


def save(proj: Project, path: str | Path, gate_undefined: str | None = None) -> None:
    Path(path).write_text(to_xml(proj, gate_undefined), encoding="utf-8")


