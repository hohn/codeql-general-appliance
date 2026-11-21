"""Shared CGAST plumbing for the cga command collection.

Every cga* command is a JSON-in / JSON-out filter: it reads a single JSON object
(the *CGAST*) from stdin, does its work, merges any new keys, and writes the
CGAST back to stdout. All human-readable and progress output goes to **stderr**,
so stdout only ever carries the CGAST and commands compose in a pipe::

    submitted=$(echo '{}' | cgadl ... | cgaql ... | cgamr ...)

CGAST is intentionally lightweight: large artifacts are written to anonymous
temporary files under ``cga/cga-tmp/`` and the CGAST just points at them, e.g.::

    { "cgaql-pack": ["cga-tmp/tmp.0AuoY4ic9M", ...] }

Stored paths are relative to the configured collection root so a state object
is portable between components in that collection. CGA and CGA preparation launchers set
different roots and sessions; sharing this plumbing does not share their state.
This module resolves stored paths back to absolute paths on read.

Standard library only, matching the rest of the cga skeleton.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict


# --- locations -------------------------------------------------------------
def cga_root() -> Path:
    """The configured collection root used to anchor relative paths."""
    env = os.environ.get("CGAST_ROOT") or os.environ.get("CGA_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    # cga/cgalib/cgast.py -> cga/
    return Path(__file__).resolve().parent.parent


def tmp_dir() -> Path:
    """The configured CGAST scratch directory (created on demand)."""
    env = os.environ.get("CGAST_TMPDIR") or os.environ.get("CGA_TMPDIR")
    d = Path(env).expanduser() if env else cga_root() / "cga-tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_tempfile(prefix: str = "tmp.", suffix: str = "") -> Path:
    """Create an anonymous temp file under cga-tmp and return its path."""
    fd, name = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=str(tmp_dir()))
    os.close(fd)
    return Path(name)


def new_tempdir(prefix: str = "tmp.") -> Path:
    """Create an anonymous temp directory under cga-tmp and return its path."""
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(tmp_dir())))


def rel(path: os.PathLike | str) -> str:
    """Represent ``path`` relative to the cga root for storage in a CGAST."""
    p = Path(path).resolve()
    try:
        return str(p.relative_to(cga_root()))
    except ValueError:
        return str(p)


def resolve(path_str: str) -> Path:
    """Resolve a CGAST-stored path (relative to cga root) to an absolute path."""
    p = Path(path_str).expanduser()
    if p.is_absolute():
        return p
    return (cga_root() / p).resolve()


# --- stdin / stdout --------------------------------------------------------
def read() -> Dict[str, Any]:
    """Read the CGAST from stdin.

    An empty stream or a tty (no piped input) is treated as ``{}`` so a command
    can start a chain interactively. Invalid input aborts with a clear message.
    """
    if sys.stdin.isatty():
        return {}
    data = sys.stdin.read()
    if not data.strip():
        return {}
    try:
        obj = json.loads(data)
    except json.JSONDecodeError as exc:
        die(f"invalid CGAST on stdin: {exc}")
    if not isinstance(obj, dict):
        die("CGAST must be a JSON object")
    return obj


def write(cgast: Dict[str, Any]) -> None:
    """Write the CGAST to stdout as a single JSON line."""
    json.dump(cgast, sys.stdout)
    sys.stdout.write("\n")
    sys.stdout.flush()


def load_session() -> Dict[str, Any]:
    """Read the serve session CGAST (``cga-tmp/session.json`` by default).

    Used by the ``serve`` viewers, which re-read it on every request so CLI
    updates show up live. A missing/unreadable session is treated as ``{}``.
    """
    env = os.environ.get("CGAST_SESSION") or os.environ.get("CGA_SESSION")
    path = Path(env).expanduser() if env else cga_root() / "cga-tmp" / "session.json"
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError):
        return {}


# --- helpers ---------------------------------------------------------------
def info(*args: object) -> None:
    """Print human/progress output to stderr (never stdout)."""
    print(*args, file=sys.stderr)


def die(msg: str, code: int = 1) -> None:
    """Print an error to stderr and exit."""
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def get(cgast: Dict[str, Any], key: str, default: Any = None) -> Any:
    """Return a CGAST value (unresolved) or ``default``."""
    return cgast.get(key, default)


def get_path(cgast: Dict[str, Any], key: str) -> Path | None:
    """Return a CGAST path value resolved to absolute, or ``None`` if absent."""
    val = cgast.get(key)
    return resolve(val) if isinstance(val, str) and val else None


def require_path(cgast: Dict[str, Any], key: str, hint: str) -> Path:
    """Return a required CGAST path, or abort with a helpful hint."""
    p = get_path(cgast, key)
    if p is None:
        die(f"missing {key!r} in CGAST ({hint})")
    return p


def set_path(cgast: Dict[str, Any], key: str, path: os.PathLike | str) -> None:
    """Store ``path`` in the CGAST under ``key`` (relative to cga root)."""
    cgast[key] = rel(path)
