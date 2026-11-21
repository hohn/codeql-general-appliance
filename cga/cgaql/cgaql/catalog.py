"""The CodeQL query catalogue for cgaql.

``cgaql index`` scans a tree of ``.ql`` files, parses each query's metadata
header (``@id``, ``@name``, ``@description``, ``@kind``, ``@problem.severity``)
and its language (the bare ``import <lang>`` line), and persists the result as a
small SQLite table ``queries``. Every other command opens that catalogue
read-only, mirroring cgadl's access to ``metadata.sql``.

The module exposes the schema, distinct values, an exact-match selector, and a
raw read-only SQL escape hatch for humans/LLMs.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

TABLE = "queries"

# Schema column order. Kept explicit so views and the JSON selection have a
# stable, predictable field order.
COLUMNS: List[str] = [
    "id",
    "name",
    "description",
    "kind",
    "severity",
    "language",
    "relpath",
    "path",
    "filename",
    "file_size",
]

# CodeQL languages recognised from a query's bare ``import <lang>`` line.
LANGUAGES = ("cpp", "python", "javascript", "java", "go", "csharp", "ruby",
             "swift")

_META_RE = re.compile(r"@([\w.]+)\s+(.*?)\s*$")
_IMPORT_RE = re.compile(r"^\s*import\s+(" + "|".join(LANGUAGES) + r")\b")


class CatalogError(RuntimeError):
    """Raised for any problem building, opening, or querying the catalogue."""


# --- building the index ----------------------------------------------------
def parse_query(path: Path, querydir: Path) -> Dict[str, Any]:
    """Parse one ``.ql`` file into a catalogue row dict."""
    text = path.read_text(encoding="utf-8", errors="replace")

    meta: Dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("*") or stripped.startswith("/**"):
            m = _META_RE.search(stripped.lstrip("*/ ").strip())
            if m:
                meta[m.group(1)] = m.group(2)
        if "select " in line and not stripped.startswith(("*", "/", "@")):
            break  # metadata header is above the query body

    language = ""
    for line in text.splitlines():
        m = _IMPORT_RE.match(line)
        if m:
            language = m.group(1)
            break

    try:
        relpath = str(path.resolve().relative_to(querydir.resolve()))
    except ValueError:
        relpath = path.name

    return {
        "id": meta.get("id", ""),
        "name": meta.get("name", ""),
        "description": meta.get("description", ""),
        "kind": meta.get("kind", ""),
        "severity": meta.get("problem.severity", ""),
        "language": language,
        "relpath": relpath,
        "path": str(path.resolve()),
        "filename": path.name,
        "file_size": path.stat().st_size,
    }


def build_index(querydir: Path, index: Path) -> int:
    """Scan ``querydir`` for ``.ql`` files and (re)write the SQLite catalogue.

    Returns the number of queries indexed.
    """
    querydir = Path(querydir)
    if not querydir.exists():
        raise CatalogError(f"query source not found: {querydir}")

    rows = [parse_query(p, querydir)
            for p in sorted(querydir.rglob("*.ql"))]

    index = Path(index)
    index.parent.mkdir(parents=True, exist_ok=True)
    if index.exists():
        index.unlink()

    conn = sqlite3.connect(str(index))
    try:
        cols = ", ".join(
            f"{c} INTEGER" if c == "file_size" else f"{c} TEXT"
            for c in COLUMNS
        )
        conn.execute(f"CREATE TABLE {TABLE} ({cols}, PRIMARY KEY (relpath))")
        conn.executemany(
            f"INSERT INTO {TABLE} ({', '.join(COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in COLUMNS)})",
            [tuple(r[c] for c in COLUMNS) for r in rows],
        )
        conn.commit()
    finally:
        conn.close()
    return len(rows)


# --- read-only access ------------------------------------------------------
def connect(index: Path) -> sqlite3.Connection:
    """Open the catalogue read-only and return a row-dict connection."""
    index = Path(index)
    if not index.exists():
        raise CatalogError(f"query index not found: {index} "
                           f"(build it with 'cgaql index')")
    uri = f"file:{index.resolve()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:  # pragma: no cover - depends on FS state
        raise CatalogError(f"cannot open {index}: {exc}") from exc
    conn.row_factory = sqlite3.Row
    return conn


def keys(conn: sqlite3.Connection) -> List[str]:
    """Return the catalogue's column names (the searchable keys)."""
    cur = conn.execute(f"PRAGMA table_info({TABLE})")
    cols = [r[1] for r in cur.fetchall()]
    return cols or list(COLUMNS)


def count(conn: sqlite3.Connection) -> int:
    """Total number of queries in the catalogue."""
    return int(conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0])


def distinct(conn: sqlite3.Connection, column: str) -> List[Any]:
    """Distinct values for one column."""
    _require_column(conn, column)
    cur = conn.execute(
        f"SELECT DISTINCT {column} FROM {TABLE} "
        f"WHERE {column} IS NOT NULL ORDER BY {column}"
    )
    return [r[0] for r in cur.fetchall()]


def sample(conn: sqlite3.Connection, limit: int = 10) -> List[sqlite3.Row]:
    """First ``limit`` rows, for a human 'list' view."""
    cur = conn.execute(f"SELECT * FROM {TABLE} ORDER BY relpath LIMIT ?",
                       (int(limit),))
    return cur.fetchall()


def select(conn: sqlite3.Connection,
           criteria: Sequence[Tuple[str, str]]) -> List[sqlite3.Row]:
    """Exact-match select on ``[(key, value), ...]`` criteria (ANDed)."""
    where = []
    params: List[str] = []
    for key, value in criteria:
        _require_column(conn, key)
        where.append(f"{key} = ?")
        params.append(value)
    sql = f"SELECT * FROM {TABLE}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY relpath"
    cur = conn.execute(sql, params)
    return cur.fetchall()


def run_sql(conn: sqlite3.Connection, sql: str) -> List[sqlite3.Row]:
    """Run an arbitrary read-only query and return its rows."""
    try:
        cur = conn.execute(sql)
    except sqlite3.Error as exc:
        raise CatalogError(f"query failed: {exc}") from exc
    return cur.fetchall()


def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert an sqlite3.Row to a plain dict (stable column order)."""
    return {k: row[k] for k in row.keys()}


def _require_column(conn: sqlite3.Connection, column: str) -> None:
    if column not in keys(conn):
        raise CatalogError(
            f"unknown key {column!r}; known keys: {', '.join(keys(conn))}")
