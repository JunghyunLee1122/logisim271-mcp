---
name: logisim-hand-drawn
description: Draw Logisim 2.7.1 circuits the way a person (or a textbook figure) would - real wires, junction dots, signal rails, few or no tunnels - and prove the wiring has no shorts/opens before opening the file. Use when generating .circ files with logisim271_mcp and the result should look hand-made, match a textbook schematic, or avoid "tunnel on every port" output.
---

# Hand-drawn Logisim schematics

Tunnel-on-every-port output works but looks machine-made. Draw with wires instead, using
`logisim271_mcp.schematic.Sheet`, which records the intended net of every wire and port and
re-checks connectivity with Logisim's own rules.

## Logisim wiring rules (2.7.1, WireRepair)
- A wire END, or ANY component port, lying on another wire (even mid-span) joins them (T junction).
- Two wires crossing mid-span do NOT connect. Crossing is fine; that is how rails work.
- Collinear overlapping wires merge (= short if they carry different nets).
- Grid is 10 px. Only horizontal / vertical segments.

## Workflow
1. Pick the textbook figure and copy its topology: inputs on the left, signal rails
   (vertical lines) for shared signals, gates in columns, outputs on the right.
2. Build with `Sheet`:
   ```python
   s = Sheet(proj, "FULL_ADDER")
   a = s.pin_in("A", (40, 100))
   x = s.gate("XOR", (220, 120), ["A", "B"], "P")     # ports dict: in0, in1, out
   s.wire("A", a, (100, 100), x["in0"])               # polyline, net name first
   s.hvh("P", x["out"], y["in0"], 260)                # h -> v at x=260 -> h
   s.check()                                          # raises on short / open / stray port
   ```
   `inst(name, loc, nets)` for subcircuits, `part(kind, loc, nets, **kw)` for library parts,
   `const`, `tunnel`, `shift(dx, dy)` to make room after drawing.
3. Run `check()` on every sheet before saving, then still simulate (evaluate / run_clocked).

## Layout patterns that never short
- **Rails + taps** (decoders, mux select, control logic): each shared signal is a vertical rail;
  every consumer gets a horizontal tap from the rail at its own port y. Keep every tap y unique
  per channel; source wires enter rails at y values no tap uses.
- **Fan-in / fan-out channel** (`fan()` in build_basic_computer.py): h-v-h routes; of the nets
  going down the topmost takes the rightmost track, of those going up the bottommost. Monotone
  fans then have zero crossings.
- **Bit stacks** (registers, adders, Fig 2-7 / 2-11 / 5-21): slices stacked vertically,
  control lines as rails on the left, data from a splitter as a staircase, outputs collected by a
  west-facing splitter, carry routed around each slice through the gap between slices.
- **Crossbar** (Fig 4-3 bus): every (source bit, mux input) gets its own horizontal track y;
  splitter ends placed in the gaps between muxes so no end x equals a mux port x
  (same x + overlapping vertical span = collinear short).
- **Arrays / diagonal feeds** (array multiplier): routes from cell k+1 to cell k of the next row
  overlap their neighbours' horizontals; alternate the horizontal y per column (k % 2). Every
  turn x of a route must differ from all rail x values (e.g. a_k rails at column x - 130).
- **Unused inputs**: one ground rail with a single constant, drops from each port.
- **Pin edges**: a pin's facing picks the instance edge (east-facing input -> west edge,
  facing north -> south edge, output facing south -> north edge). Use it to put LD/INR/CLR
  under register boxes and select lines on top of muxes like the textbook.
- Tunnels only where the textbook itself just labels a line (control signals, clock in the
  top-level datapath).

## Checker messages
- `short: A (...), B (...)` - two nets touch; usually equal y of two horizontals in one channel
  or a port lying on a passing wire.
- `open: net X in k pieces` - a rail does not reach a tap, or a junction point misses the wire.
- `stray: [...] touches [...]` - an undeclared port (e.g. Qn) sits on a wire.
