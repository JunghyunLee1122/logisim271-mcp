"""Run Logisim 2.7.1 headless (``-tty table``) and capture the first output line.

Logisim 2.7.1's tty mode prints one tab-separated line with every output
pin's value once the circuit settles, then keeps running forever. We read
that first line and kill the JVM.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from pathlib import Path

DEFAULT_TIMEOUT = 30.0


def find_jar() -> Path:
    env = os.environ.get("LOGISIM_JAR")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        for name in ("logisim-win-2.7.1.exe", "logisim-generic-2.7.1.jar", "logisim.jar"):
            cand = parent / name
            if cand.exists():
                return cand
    raise FileNotFoundError(
        "Logisim 2.7.1 not found. Set LOGISIM_JAR to logisim-win-2.7.1.exe or the 2.7.1 jar."
    )


def find_java() -> str:
    return os.environ.get("JAVA") or shutil.which("java") or "java"


class SimError(RuntimeError):
    pass


def run_tty_lines(circ_path: str | Path, n: int, timeout: float = DEFAULT_TIMEOUT) -> list[list[str]]:
    """Read the first ``n`` tty lines (tty prints a line whenever outputs change;
    clocks keep ticking), then kill the JVM. Each line is split on tabs."""
    cmd = [find_java(), "-Djava.awt.headless=true", "-jar", str(find_jar()),
           str(circ_path), "-tty", "table"]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    lines: list[str] = []

    def reader() -> None:
        assert proc.stdout is not None
        while len(lines) < n:
            raw = proc.stdout.readline()
            if not raw:
                break
            s = raw.decode("utf-8", "replace").strip("\r\n")
            if s:
                lines.append(s)

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    t.join(timeout)
    stderr = b""
    try:
        proc.kill()
        _, stderr = proc.communicate(timeout=5)
    except Exception:
        pass
    if len(lines) < n:
        msg = stderr.decode("utf-8", "replace").strip()
        raise SimError(f"Logisim printed {len(lines)}/{n} lines (timeout {timeout}s). {msg[:500]}")
    return [l.split("\t") for l in lines[:n]]


def run_tty(circ_path: str | Path, timeout: float = DEFAULT_TIMEOUT) -> list[str]:
    """Return the values of all output pins (tty column order) for one settle."""
    return run_tty_lines(circ_path, 1, timeout)[0]
