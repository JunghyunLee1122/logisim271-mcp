"""load() -> save() must not drop parts of a .circ file this model does not
interpret (custom appearance, options, toolbar, library tool defaults,
circuit attributes, multi-line attribute values)."""

import xml.etree.ElementTree as ET

import pytest

from logisim271_mcp import model, runner

try:
    runner.find_jar()
    HAVE_LOGISIM = True
except FileNotFoundError:
    HAVE_LOGISIM = False

SAMPLE = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<project source="2.7.1" version="1.0">
This file is intended to be loaded by Logisim (http://www.cburch.com/logisim/).
  <lib desc="#Wiring" name="0">
    <tool name="Splitter">
      <a name="fanout" val="4"/>
    </tool>
  </lib>
  <lib desc="#Gates" name="1"/>
  <lib desc="#Memory" name="2"/>
  <lib desc="#Base" name="3"/>
  <main name="main"/>
  <options>
    <a name="gateUndefined" val="error"/>
    <a name="simlimit" val="5000"/>
    <a name="simrand" val="0"/>
  </options>
  <mappings>
    <tool lib="3" map="Button2" name="Menu Tool"/>
  </mappings>
  <toolbar>
    <tool lib="3" name="Poke Tool"/>
    <sep/>
    <tool lib="1" name="AND Gate"/>
  </toolbar>
  <circuit name="main">
    <a name="circuit" val="main"/>
    <a name="clabel" val="TOP"/>
    <a name="circuitnamedbox" val="false"/>
    <appear>
      <rect height="40" stroke="#000000" width="30" x="50" y="50"/>
      <circ-port height="8" pin="60,70" width="8" x="46" y="66"/>
      <circ-anchor facing="east" height="6" width="6" x="77" y="67"/>
    </appear>
    <wire from="(60,70)" to="(100,70)"/>
    <comp lib="0" loc="(60,70)" name="Pin">
      <a name="label" val="A"/>
    </comp>
    <comp lib="2" loc="(200,100)" name="ROM">
      <a name="contents">addr/data: 8 8
1 2 3 4
</a>
    </comp>
  </circuit>
</project>
"""


def _roundtrip(tmp_path, gate_undefined=None):
    src = tmp_path / "in.circ"
    src.write_text(SAMPLE, encoding="utf-8")
    proj = model.load(src)
    out = tmp_path / "out.circ"
    model.save(proj, out, gate_undefined=gate_undefined)
    return ET.parse(out).getroot(), proj


def _opts(root):
    return {a.get("name"): a.get("val") for a in root.find("options").findall("a")}


def test_preserves_unknown_parts(tmp_path):
    root, _ = _roundtrip(tmp_path)
    assert _opts(root) == {"gateUndefined": "error", "simlimit": "5000", "simrand": "0"}
    circ = root.find("circuit")
    assert circ.find("appear/circ-port").get("pin") == "60,70"
    attrs = {a.get("name"): a.get("val") for a in circ.findall("a")}
    assert attrs == {"circuit": "main", "clabel": "TOP", "circuitnamedbox": "false"}
    wiring = root.find("lib[@desc='#Wiring']")
    assert wiring.find("tool[@name='Splitter']/a").get("val") == "4"
    rom = circ.find("comp[@name='ROM']/a[@name='contents']")
    assert rom.text.splitlines() == ["addr/data: 8 8", "1 2 3 4"]


def test_lib_refs_follow_library_indices(tmp_path):
    root, _ = _roundtrip(tmp_path)
    desc = {lib.get("name"): lib.get("desc") for lib in root.findall("lib")}
    assert [desc[t.get("lib")] for t in root.find("toolbar").findall("tool")] == ["#Base", "#Gates"]
    assert desc[root.find("mappings/tool").get("lib")] == "#Base"


def test_lib_refs_survive_library_reorder(tmp_path):
    src = tmp_path / "in.circ"
    src.write_text(SAMPLE, encoding="utf-8")
    proj = model.load(src)
    proj.libs.reverse()  # indices change; preserved refs must be remapped
    out = tmp_path / "out.circ"
    model.save(proj, out)
    root = ET.parse(out).getroot()
    desc = {lib.get("name"): lib.get("desc") for lib in root.findall("lib")}
    assert [desc[t.get("lib")] for t in root.find("toolbar").findall("tool")] == ["#Base", "#Gates"]
    assert desc[root.find("circuit/comp[@name='ROM']").get("lib")] == "#Memory"


def test_explicit_gate_undefined_overrides(tmp_path):
    root, _ = _roundtrip(tmp_path, gate_undefined="ignore")
    assert _opts(root)["gateUndefined"] == "ignore"
    assert _opts(root)["simlimit"] == "5000"


def test_second_roundtrip_is_stable(tmp_path):
    src = tmp_path / "in.circ"
    src.write_text(SAMPLE, encoding="utf-8")
    a = model.to_xml(model.load(src))
    (tmp_path / "a.circ").write_text(a, encoding="utf-8")
    assert model.to_xml(model.load(tmp_path / "a.circ")) == a


def test_new_project_uses_template(tmp_path):
    proj = model.Project()
    proj.add_circuit("main")
    root = ET.fromstring(model.to_xml(proj))
    assert _opts(root)["gateUndefined"] == "ignore"
    assert root.find("toolbar") is not None


ROM_CIRC = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<project source="2.7.1" version="1.0">
  <lib desc="#Wiring" name="0"/>
  <lib desc="#Memory" name="1"/>
  <lib desc="#Base" name="2"/>
  <main name="main"/>
  <options>
    <a name="gateUndefined" val="ignore"/>
    <a name="simlimit" val="1000"/>
    <a name="simrand" val="0"/>
  </options>
  <circuit name="main">
    <a name="circuit" val="main"/>
    <wire from="(100,100)" to="(160,100)"/>
    <wire from="(300,100)" to="(340,100)"/>
    <comp lib="0" loc="(100,100)" name="Constant">
      <a name="width" val="8"/>
      <a name="value" val="0x2"/>
    </comp>
    <comp lib="1" loc="(300,100)" name="ROM">
      <a name="contents">addr/data: 8 8
1 2 3 4
</a>
    </comp>
    <comp lib="0" loc="(340,100)" name="Pin">
      <a name="facing" val="west"/>
      <a name="output" val="true"/>
      <a name="width" val="8"/>
      <a name="label" val="Q"/>
    </comp>
  </circuit>
</project>
"""


@pytest.mark.skipif(not HAVE_LOGISIM, reason="Logisim 2.7.1 not found")
def test_rom_contents_survive_in_real_logisim(tmp_path):
    # ROM contents are element text, not val=""; dropping them made Logisim
    # throw NullPointerException in Rom.configureNewInstance on load.
    src = tmp_path / "in.circ"
    src.write_text(ROM_CIRC, encoding="utf-8")
    out = tmp_path / "out.circ"
    model.save(model.load(src), out)
    assert runner.run_tty(out) == ["0000 0011"]  # word at address 2


def test_custom_appearance_subcircuit_has_no_default_ports(tmp_path):
    from logisim271_mcp import library as L
    src = tmp_path / "in.circ"
    src.write_text(SAMPLE, encoding="utf-8")
    proj = model.load(src)
    inst = model.Component(None, "main", (300, 300))
    assert L.ports(inst, proj) is None  # "main" has <appear>; default layout would lie
