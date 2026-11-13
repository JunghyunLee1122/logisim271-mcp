# logisim271-mcp

MCP server that builds and verifies circuits as **Logisim 2.7.1** `.circ` files
(classic Carl Burch Logisim, not Evolution). Simulation runs the real 2.7.1
via `java -jar logisim-win-2.7.1.exe file.circ -tty table`.

## Tools

| Group | Tools |
|---|---|
| File | `create_circuit_file`, `list_circuits`, `add_circuit`, `delete_circuit`, `set_main_circuit`, `describe_circuit` |
| Low level | `add_pin`, `add_gate`, `add_component` (flip-flops, register, counter, mux, adder/subtractor), `add_constant`, `add_wire`, `add_subcircuit_instance`, `remove` |
| High level | `build_logic` (expressions), `build_preset` (half/full/ripple adder, mux, decoder, comparator), `build_from_truth_table` (Quine-McCluskey) |
| Simulation | `simulate`, `truth_table`, `verify_truth_table`, `simulate_sequential` (clocked circuits, optional per-cycle input `sequence`) |

High-level builders auto-place and auto-wire, then verify the full truth table in Logisim.

## 2.7.1 facts this relies on (all measured, see `tests/`)

- Gate `loc` = output point. Size 50 input offsets (east): 2 → ±20; 3 → -20,0,20;
  4 → -20,-10,10,20; 5 → -20..20 step 10. Input x = loc − 50 (AND/OR), −60 (NAND/NOR, XOR),
  −70 (XNOR), −30 (NOT), −20 (Buffer).
- Default `inputs` is 5; XOR default is "exactly one" → we write `xor="odd"` (parity).
- `-tty table` settles once with input pins at 0 (pin values aren't saved), prints output
  pins sorted by (y, x), tab-separated, multi-bit as binary, `x` floating / `E` error, then
  never exits. We read one line and kill the JVM. To evaluate many rows in one run, the
  circuit is copied once per row with input pins replaced by Constants.
- A wire end touching another wire mid-span connects; mid-span crossings don't.
- tty mode **does tick Clock components** and prints a line each time an output
  changes. `simulate_sequential` replaces the clock pin with a Clock and adds a second
  Clock wired to a top-most output pin, so every half period yields one line
  (line 0 = power-on, line 2k-1 = after rising edge k). Non-clock inputs are held
  constant unless `sequence` is given: then each sequenced input pin becomes a Tunnel
  fed by a Multiplexer of Constants whose select comes from a Counter clocked on the
  falling edge, so step k is in place before rising edge k+1 (max 16 steps).
- Large `simulate`/`truth_table` batches are split into runs of about 8000
  components+wires (one huge run takes minutes to load) executed 4 at a time.

## Library component ports (east-facing, offsets from `loc`)

Read from the 2.7.1 class files and checked in `tests/test_components.py`.

| Component | Ports |
|---|---|
| D / T Flip-Flop | D or T (-40,20), clock (-40,0), Q (0,0), Qn (0,20), preset (-30,30), enable (-20,30), reset (-10,30) |
| J-K / S-R Flip-Flop | J or S (-40,0), K or R (-40,20), clock (-40,10), rest as D |
| Register | out (0,0), data (-30,0), enable (-30,10), clock (-20,20), clear (-10,20) |
| Counter | out (0,0), data (-30,0), load (-30,-10), count (-30,10), clock (-20,20), clear (-10,20), carry (0,10) |
| Multiplexer, 2 inputs | in0 (-30,-10), in1 (-30,10), select (-20,20) |
| Multiplexer, n = 4/8/16 | in_i (-40, -n/2·10 + 10i), select (-20, n/2·10), out (0,0) — note the inputs are not centred |
| Adder / Subtractor | A (-40,-10), B (-40,10), out (0,0), carry/borrow in (-20,-20), out (-20,20) |

Note the D flip-flop's clock is the *upper* input and D the lower one.

## Hand-drawn schematics (`logisim271_mcp.schematic`)

For Python scripts that should produce a schematic a person could have drawn (real wires,
junctions, signal rails, few tunnels) instead of a tunnel on every port. `Sheet` records the
intended net of every wire and port, and `check()` recomputes connectivity with Logisim's own
rules, reporting `short`, `open`, `stray` and `unconnected` with coordinates before the file is opened.

```python
from logisim271_mcp.model import Project
from logisim271_mcp.schematic import Sheet

proj = Project()
s = Sheet(proj, "FULL_ADDER")
a = s.pin_in("A", (40, 100))
x = s.gate("XOR", (220, 120), ["A", "B"], "P")   # returns port points: in0, in1, out
s.wire("A", a, (100, 100), x["in0"])             # polyline, net name first
s.hvh("P", x["out"], (300, 140), 260)            # horizontal, vertical at x=260, horizontal
s.check()                                        # raises SchematicError on short / open
```

Other helpers: `pin_out`, `const`, `part` (library parts), `inst` (subcircuits), `tunnel`,
`hv` / `vh` / `vhv`, `shift(dx, dy)`. Splitters accept `facing` east / west / north / south.

Layout patterns and checker messages are in the Claude Code skill
[`skills/logisim-hand-drawn/SKILL.md`](skills/logisim-hand-drawn/SKILL.md). Install it by copying the
folder to `~/.claude/skills/`.

## Install (Claude Code)

Requirements: Java 8+, Python 3.10+, [uv](https://docs.astral.sh/uv/), and Logisim 2.7.1
(`logisim-win-2.7.1.exe` or `logisim-generic-2.7.1.jar` from
[SourceForge](https://sourceforge.net/projects/circuit/files/2.7.x/2.7.1/)). Logisim is not bundled.

### Option A: plugin (MCP server + skill in one step)

1. Set the `LOGISIM_JAR` environment variable to your Logisim 2.7.1 exe/jar path
   (e.g. `setx LOGISIM_JAR C:/path/to/logisim-win-2.7.1.exe` on Windows), then restart your terminal.
2. In Claude Code:

```
/plugin marketplace add JunghyunLee1122/logisim271-mcp
/plugin install logisim271@logisim271-mcp
```

Restart Claude Code. This installs the `logisim271` MCP server and the `logisim-hand-drawn` skill.

### Option B: MCP server only

```bash
claude mcp add logisim271 --env LOGISIM_JAR=C:/path/to/logisim-win-2.7.1.exe -- uvx --from git+https://github.com/JunghyunLee1122/logisim271-mcp logisim271-mcp
```

### Option C: Codex CLI

Codex does not read `.claude-plugin`, so register the MCP server and the skill separately.

```bash
codex mcp add logisim271 --env LOGISIM_JAR=C:/path/to/logisim-win-2.7.1.exe -- uvx --from git+https://github.com/JunghyunLee1122/logisim271-mcp logisim271-mcp
```

Or add it to `~/.codex/config.toml`:

```toml
[mcp_servers.logisim271]
command = "uvx"
args = ["--from", "git+https://github.com/JunghyunLee1122/logisim271-mcp", "logisim271-mcp"]
env = { LOGISIM_JAR = "C:/path/to/logisim-win-2.7.1.exe" }
```

Skill: copy `skills/logisim-hand-drawn/` into `~/.codex/skills/` (some Codex versions use
`~/.agents/skills/` instead), then start a new Codex session.

```bash
git clone https://github.com/JunghyunLee1122/logisim271-mcp.git
cp -r logisim271-mcp/skills/logisim-hand-drawn ~/.codex/skills/
```

Then ask e.g. "full adder 만들어줘" / "build a 4-bit ripple adder in adder.circ and verify it".

## Development

```bash
py -3.13 -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"
LOGISIM_JAR=../logisim-win-2.7.1.exe .venv/Scripts/python.exe -m pytest
```

Env: `LOGISIM_JAR` (2.7.1 exe or jar), `JAVA` (java executable), `LOGISIM_WORKDIR` (base for relative paths).
