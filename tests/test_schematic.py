import pytest

from logisim271_mcp import library as L
from logisim271_mcp.model import Project
from logisim271_mcp.schematic import SchematicError, Sheet


def sheet():
    return Sheet(Project(main="m"), "m")


def test_clean_t_junction_and_crossing():
    s = sheet()
    a = s.pin_in("A", (40, 100))
    b = s.pin_in("B", (40, 200))
    s.wire("A", a, (100, 100), (100, 300))
    s.wire("A", (100, 200 - 50), (200, 150))      # T junction mid-span
    s.wire("B", b, (300, 200))                    # crosses the A rail mid-span
    s.check()


def test_short_by_endpoint_on_wire():
    s = sheet()
    s.pin_in("A", (40, 100))
    s.pin_in("B", (40, 200))
    s.wire("A", (40, 100), (100, 100), (100, 300))
    s.wire("B", (40, 200), (100, 200))            # ends on the A rail
    with pytest.raises(SchematicError, match="short"):
        s.check()


def test_collinear_overlap_shorts_and_open_detected():
    s = sheet()
    s.wire("A", (0, 0), (100, 0))
    s.wire("B", (50, 0), (150, 0))
    s.wire("C", (0, 50), (10, 50))
    s.wire("C", (30, 50), (40, 50))
    with pytest.raises(SchematicError) as e:
        s.check()
    assert "short" in str(e.value) and "open: net C" in str(e.value)


def test_splitter_facings():
    for facing, first in [("east", (20, -20)), ("west", (-20, 10)), ("south", (20, 20)),
                          ("north", (-10, -20))]:
        sp = L.component("splitter", (0, 0), width=2, splits=[1, 1], facing=facing)
        assert L.ports(sp)["split0"] == first
