"""Read-only access to the CodeQL DB catalogue (``metadata.sql``).

The catalogue is a single SQLite table, ``metadata``, one row per CodeQL
database. cgadl never writes to it; construction and maintenance belong to
CGA preparation. This module exposes the schema, distinct values, a simple
exact-match selector, and a raw read-only SQL escape hatch for humans/LLMs.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

TABLE = "metadata"

# Explicit schema column order keeps views and JSON selections stable.
COLUMNS: List[str] = [
    "content_hash",
    "build_cid",
    "git_branch",
    "git_commit_id",
    "git_owner",
    "git_repo",
    "ingestion_datetime_utc",
    "primary_language",
    "result_url",
    "tool_name",
    "tool_version",
    "projname",
    "db_file_size",
]


class CatalogError(RuntimeError):
    """Raised for any problem opening or querying the catalogue."""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open the catalogue read-only and return a row-dict connection."""
    db_path = Path(db_path)
    if not db_path.exists():
        raise CatalogError(f"metadata.sql not found: {db_path} "
                           f"(fetch it with 'cgadl getmeta <url>')")
    # Resolve symlinks so the sqlite3 URI opens the real file.
    uri = f"file:{db_path.resolve()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:  # pragma: no cover - depends on FS state
        raise CatalogError(f"cannot open {db_path}: {exc}") from exc
    conn.row_factory = sqlite3.Row
    return conn


def keys(conn: sqlite3.Connection) -> List[str]:
    """Return the catalogue's column names (the searchable keys)."""
    cur = conn.execute(f"PRAGMA table_info({TABLE})")
    cols = [r[1] for r in cur.fetchall()]
    return cols or list(COLUMNS)


def count(conn: sqlite3.Connection) -> int:
    """Total number of databases in the catalogue."""
    return int(conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0])


def distinct(conn: sqlite3.Connection, column: str) -> List[Any]:
    """Distinct values for one column (used by the human 'view' of keys)."""
    _require_column(conn, column)
    cur = conn.execute(
        f"SELECT DISTINCT {column} FROM {TABLE} "
        f"WHERE {column} IS NOT NULL ORDER BY {column}"
    )
    return [r[0] for r in cur.fetchall()]


def sample(conn: sqlite3.Connection, limit: int = 10) -> List[sqlite3.Row]:
    """First ``limit`` rows, for a human 'list' view."""
    cur = conn.execute(f"SELECT * FROM {TABLE} LIMIT ?", (int(limit),))
    return cur.fetchall()


def select(conn: sqlite3.Connection,
           criteria: Sequence[Tuple[str, str]]) -> List[sqlite3.Row]:
    """Exact-match select on ``[(key, value), ...]`` criteria (ANDed).

    For anything richer (LIKE, regex, ranges) use :func:`run_sql`.
    """
    where = []
    params: List[str] = []
    for key, value in criteria:
        _require_column(conn, key)
        where.append(f"{key} = ?")
        params.append(value)
    sql = f"SELECT * FROM {TABLE}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    cur = conn.execute(sql, params)
    return cur.fetchall()


def run_sql(conn: sqlite3.Connection, sql: str) -> List[sqlite3.Row]:
    """Run an arbitrary read-only query and return its rows.

    The connection is opened read-only, so writes fail at the SQLite level;
    this is the intended escape hatch for humans and LLMs.
    """
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
