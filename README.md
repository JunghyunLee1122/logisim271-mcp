# logisim271-mcp

MCP server that builds and verifies circuits as **Logisim 2.7.1** `.circ` files
(classic Carl Burch Logisim, not Evolution). Simulation runs the real 2.7.1
via `java -jar logisim-win-2.7.1.exe file.circ -tty table`.

## Tools

| Group | Tools |
|---|---|
| File | `create_circuit_file`, `list_circuits`, `add_circuit`, `delete_circuit`, `set_main_circuit`, `describe_circuit` |
| Low level | `add_pin`, `add_gate`, `add_constant`, `add_wire`, `add_subcircuit_instance`, `remove` |
| High level | `build_logic` (expressions), `build_preset` (half/full/ripple adder, mux, decoder, comparator), `build_from_truth_table` (Quine-McCluskey) |
| Simulation | `simulate`, `truth_table`, `verify_truth_table`, `simulate_sequential` (clocked circuits) |

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
  constant for the whole run (no per-cycle input sequences yet).

## Install (Claude Code)

Requirements: Java 8+, Python 3.10+, [uv](https://docs.astral.sh/uv/), and Logisim 2.7.1
(`logisim-win-2.7.1.exe` or `logisim-generic-2.7.1.jar` from
[SourceForge](https://sourceforge.net/projects/circuit/files/2.7.x/2.7.1/)). Logisim is not bundled.

```bash
claude mcp add logisim271 --env LOGISIM_JAR=C:/path/to/logisim-win-2.7.1.exe -- uvx --from git+https://github.com/JunghyunLee1122/logisim271-mcp logisim271-mcp
```

Then ask e.g. "full adder 만들어줘" / "build a 4-bit ripple adder in adder.circ and verify it".

## Development

```bash
py -3.13 -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"
LOGISIM_JAR=../logisim-win-2.7.1.exe .venv/Scripts/python.exe -m pytest
```

Env: `LOGISIM_JAR` (2.7.1 exe or jar), `JAVA` (java executable), `LOGISIM_WORKDIR` (base for relative paths).
