"""Read-only DuckDB access for the cumulative cgasi result store."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

TABLE = "sarif_results"
COLUMNS = [
    "user",
    "file_name",
    "kind",
    "rule_id",
    "rule_name",
    "uri",
    "start_line",
    "start_column",
    "result_json",
]
DISPLAY_COLUMNS = COLUMNS[:-1]

# The Findings view: which display labels the fragment shows, the SQL column
# each label filters on, the entry-row-count (ERC) choices, and the default.
FILTER_COLUMNS = {
    "user": "user",
    "rule": "rule_id",
    "kind": "kind",
    "uri": "uri",
    "line": "start_line",
}
FILTER_ORDER = ["user", "rule", "kind", "uri", "line"]
ERC_CHOICES = (10, 40, 100)
DEFAULT_ERC = 10


class StoreError(RuntimeError):
    """The cumulative database is missing, invalid, or cannot be queried."""


def _quote(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def query(db_path: Path, sql: str, *, restricted: bool = False,
          timeout: int | None = None) -> List[Dict[str, Any]]:
    """Execute one read-only DuckDB query and return JSON rows."""
    db_path = Path(db_path)
    if not db_path.is_file():
        raise StoreError(f"database not found: {db_path}")
    duckdb = shutil.which("duckdb")
    if not duckdb:
        raise StoreError("required command not found: duckdb")
    arguments = [duckdb, "-readonly", "-json"]
    if restricted:
        arguments += ["-safe", "-no-init", "-bail"]
    try:
        proc = subprocess.run(
            [*arguments, str(db_path), "-c", sql],
            text=True, capture_output=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise StoreError(f"DuckDB query exceeded {timeout} seconds") from exc
    if proc.returncode != 0:
        raise StoreError(proc.stderr.strip() or proc.stdout.strip()
                         or "DuckDB query failed")
    if not proc.stdout.strip():
        return []
    try:
        value = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise StoreError(f"invalid JSON from duckdb: {exc}") from exc
    if not isinstance(value, list) or any(not isinstance(row, dict)
                                         for row in value):
        raise StoreError("unexpected result from duckdb")
    return value


def keys(db_path: Path) -> List[str]:
    rows = query(
        db_path,
        "select name from pragma_table_info('sarif_results') order by cid",
    )
    return [str(row["name"]) for row in rows]


def count(db_path: Path) -> int:
    rows = query(db_path, f"select count(*) as n from {TABLE}")
    return int(rows[0]["n"]) if rows else 0


def distinct(db_path: Path, column: str) -> List[Any]:
    _require_column(db_path, column)
    rows = query(
        db_path,
        f"select distinct {column} as value from {TABLE} "
        f"where {column} is not null order by {column}",
    )
    return [row["value"] for row in rows]


def sample(db_path: Path, limit: int = 20) -> List[Dict[str, Any]]:
    limit = max(0, int(limit))
    columns = ", ".join(DISPLAY_COLUMNS)
    return query(
        db_path,
        f"select {columns} from {TABLE} "
        "order by user, file_name, uri, start_line, start_column "
        f"limit {limit}",
    )


def find(db_path: Path, filters: Dict[str, str],
         limit: int) -> List[Dict[str, Any]]:
    """Return findings matching each non-empty per-column regex, up to limit.

    ``filters`` maps display labels in ``FILTER_ORDER`` to regular expressions;
    an empty or missing pattern matches everything. Regex matching is partial
    (DuckDB ``regexp_matches``), so ``.`` alone matches any non-empty value.
    """
    limit = max(0, int(limit))
    filters = filters or {}
    where = []
    for label in FILTER_ORDER:
        pattern = str(filters.get(label, "") or "")
        if not pattern:
            continue
        column = FILTER_COLUMNS[label]
        where.append(
            f"regexp_matches(cast({column} as varchar), {_quote(pattern)})")
    columns = ", ".join(DISPLAY_COLUMNS)
    sql = f"select {columns} from {TABLE}"
    if where:
        sql += " where " + " and ".join(where)
    sql += (" order by user, file_name, uri, start_line, start_column"
            f" limit {limit}")
    return query(db_path, sql)


def select(db_path: Path,
           criteria: Sequence[Tuple[str, str]]) -> List[Dict[str, Any]]:
    return query(db_path, selection_sql(db_path, criteria))


def selection_sql(db_path: Path, criteria: Sequence[Tuple[str, str]],
                  *, include_result: bool = False) -> str:
    """Build the same exact-match query used by ``cgasi search``."""
    where = []
    for key, value in criteria:
        _require_column(db_path, key)
        where.append(f"{key} = {_quote(value)}")
    columns = ", ".join(COLUMNS if include_result else DISPLAY_COLUMNS)
    sql = f"select {columns} from {TABLE}"
    if where:
        sql += " where " + " and ".join(where)
    sql += " order by user, file_name, uri, start_line, start_column"
    return sql


def query_page(db_path: Path, sql: str, offset: int = 0,
               limit: int = 30) -> Dict[str, Any]:
    """Page one SELECT/CTE, without filesystem/network access or SQL side effects."""
    if (not isinstance(offset, int) or isinstance(offset, bool) or offset < 0
            or not isinstance(limit, int) or isinstance(limit, bool)
            or not 1 <= limit <= 100):
        raise StoreError("offset must be nonnegative; limit must be 1..100")
    if not isinstance(sql, str) or not sql.strip() or len(sql.encode("utf-8")) > 32768:
        raise StoreError("SQL must contain 1..32768 UTF-8 bytes")

    def read(statement: str) -> List[Dict[str, Any]]:
        return query(db_path, statement, restricted=True, timeout=15)

    # DuckDB's parser handles quoted semicolons/comments and normalizes the
    # single SELECT before embedding it. Text-based keyword checks are unsafe.
    serialized = read(
        f"select cast(json_serialize_sql({_quote(sql)}) as varchar) as parsed")[0]["parsed"]
    parsed = json.loads(serialized)
    if parsed.get("error"):
        raise StoreError(parsed.get("error_message", "expected a SELECT query"))
    if len(parsed.get("statements", [])) != 1:
        raise StoreError("exactly one SELECT or WITH query is required")
    normalized = read(
        f"select json_deserialize_sql({_quote(serialized)}) as sql")[0]["sql"]
    relation = f"({normalized}) as bench_results"
    columns = [row["column_name"] for row in read(f"describe select * from {relation}")]
    total = int(read(f"select count(*) as n from {relation}")[0]["n"])
    rows = read(f"select * from {relation} limit {limit} offset {offset}")
    return {"columns": columns, "rows": rows, "total": total,
            "offset": offset, "limit": limit, "has_more": offset + limit < total}


def run_sql(db_path: Path, sql: str) -> List[Dict[str, Any]]:
    if not sql.strip():
        raise StoreError("SQL query is empty")
    return query(db_path, sql)


def _require_column(db_path: Path, column: str) -> None:
    known = keys(db_path)
    if column not in known:
        raise StoreError(
            f"unknown key {column!r}; known keys: {', '.join(known)}")
