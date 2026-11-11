"""Truth table -> minimal sum-of-products (Quine-McCluskey + greedy cover),
and expression presets for the classic textbook circuits."""

from __future__ import annotations

from itertools import combinations


def _combine(a: str, b: str) -> str | None:
    diff = 0
    out = []
    for x, y in zip(a, b):
        if x != y:
            if x == "-" or y == "-":
                return None
            diff += 1
            out.append("-")
        else:
            out.append(x)
    return "".join(out) if diff == 1 else None


def minimize(n: int, minterms: list[int], dontcares: list[int] = ()) -> list[str]:
    """Return prime-implicant cover as patterns like '1-0' (MSB = first var)."""
    ones = set(minterms)
    if not ones:
        return []
    terms = {format(m, f"0{n}b") for m in ones | set(dontcares)}
    primes: set[str] = set()
    while terms:
        used = set()
        nxt = set()
        tl = sorted(terms)
        for a, b in combinations(tl, 2):
            c = _combine(a, b)
            if c:
                nxt.add(c); used.add(a); used.add(b)
        primes |= terms - used
        terms = nxt

    def covers(p: str, m: int) -> bool:
        bits = format(m, f"0{n}b")
        return all(pc == "-" or pc == bc for pc, bc in zip(p, bits))

    remaining = set(ones)
    chosen: list[str] = []
    # essential primes first
    for m in sorted(ones):
        cov = [p for p in primes if covers(p, m)]
        if len(cov) == 1 and cov[0] not in chosen:
            chosen.append(cov[0])
    for p in chosen:
        remaining -= {m for m in remaining if covers(p, m)}
    while remaining:
        best = max(sorted(primes), key=lambda p: (sum(covers(p, m) for m in remaining), p.count("-")))
        chosen.append(best)
        remaining -= {m for m in remaining if covers(best, m)}
    return chosen


def sop(names: list[str], minterms: list[int], dontcares: list[int] = ()) -> str:
    n = len(names)
    if set(minterms) | set(dontcares) >= set(range(1 << n)) and minterms:
        return "1"
    cover = minimize(n, minterms, dontcares)
    if not cover:
        return "0"
    terms = []
    for p in cover:
        lits = [(v if c == "1" else f"~{v}") for v, c in zip(names, p) if c != "-"]
        terms.append(" & ".join(lits) if lits else "1")
    if "1" in terms:
        return "1"
    return " | ".join(f"({t})" if "&" in t and len(cover) > 1 else t for t in terms)


# --------------------------------------------------------------------------- presets

def half_adder() -> tuple[list[str], dict[str, str]]:
    return ["A", "B"], {"S": "A ^ B", "C": "A & B"}


def full_adder() -> tuple[list[str], dict[str, str]]:
    return ["A", "B", "Cin"], {"S": "A ^ B ^ Cin", "Cout": "(A & B) | (Cin & (A ^ B))"}


def ripple_adder(bits: int) -> tuple[list[str], dict[str, str]]:
    if not 1 <= bits <= 8:
        raise ValueError("bits must be 1..8")
    ins = [f"A{i}" for i in range(bits)] + [f"B{i}" for i in range(bits)] + ["Cin"]
    outs: dict[str, str] = {}
    carry = "Cin"
    for i in range(bits):
        a, b = f"A{i}", f"B{i}"
        outs[f"S{i}"] = f"{a} ^ {b} ^ ({carry})"
        carry = f"({a} & {b}) | (({carry}) & ({a} ^ {b}))"
    outs["Cout"] = carry
    return ins, outs


def mux(select_bits: int) -> tuple[list[str], dict[str, str]]:
    if not 1 <= select_bits <= 3:
        raise ValueError("select_bits must be 1..3")
    n = 1 << select_bits
    sel = [f"S{i}" for i in range(select_bits)]
    data = [f"D{i}" for i in range(n)]
    terms = []
    for i in range(n):
        lits = [sel[b] if (i >> b) & 1 else f"~{sel[b]}" for b in reversed(range(select_bits))]
        terms.append("(" + " & ".join(lits + [data[i]]) + ")")
    return data + list(reversed(sel)), {"Y": " | ".join(terms)}


def decoder(bits: int, enable: bool = False) -> tuple[list[str], dict[str, str]]:
    if not 1 <= bits <= 3:
        raise ValueError("bits must be 1..3")
    sel = [f"A{i}" for i in reversed(range(bits))]
    outs = {}
    for i in range(1 << bits):
        lits = [f"A{b}" if (i >> b) & 1 else f"~A{b}" for b in reversed(range(bits))]
        if enable:
            lits.append("EN")
        outs[f"Y{i}"] = " & ".join(lits) if len(lits) > 1 else lits[0]
    return sel + (["EN"] if enable else []), outs


def comparator(bits: int) -> tuple[list[str], dict[str, str]]:
    """Unsigned magnitude comparator: EQ, GT (A>B), LT (A<B)."""
    if not 1 <= bits <= 4:
        raise ValueError("bits must be 1..4")
    ins = [f"A{i}" for i in reversed(range(bits))] + [f"B{i}" for i in reversed(range(bits))]
    x = {i: f"~(A{i} ^ B{i})" for i in range(bits)}  # bit equal
    gt_terms, lt_terms = [], []
    for i in reversed(range(bits)):
        prefix = [x[j] for j in range(i + 1, bits)]
        gt_terms.append(" & ".join(prefix + [f"A{i} & ~B{i}"]))
        lt_terms.append(" & ".join(prefix + [f"~A{i} & B{i}"]))
    eq = " & ".join(x[i] for i in reversed(range(bits)))
    return ins, {
        "EQ": eq,
        "GT": " | ".join(f"({t})" for t in gt_terms),
        "LT": " | ".join(f"({t})" for t in lt_terms),
    }


PRESETS = {
    "half_adder": lambda **k: half_adder(),
    "full_adder": lambda **k: full_adder(),
    "ripple_adder": lambda bits=4, **k: ripple_adder(bits),
    "mux": lambda select_bits=1, **k: mux(select_bits),
    "decoder": lambda bits=2, enable=False, **k: decoder(bits, enable),
    "comparator": lambda bits=2, **k: comparator(bits),
}
