"""cgasi: CGAST-aware cumulative SARIF ingestion and query client."""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import subprocess
import sys
import zipfile
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List

import cgast
from command_help import enhance_parser

from . import serve, store

COMPONENT = "cgasi"
DEFAULT_PORT = 8606
DB_KEY = "cgasi-db"
QUERY_KEY = "cgasi-query"
SQLITES_KEY = "cgasi-sqlites"
INGESTIONS_KEY = "cgasi-ingestions"
ROOT_KEY = "cgasi-root"
ACTIVE_KEY = "cgasi-active"
VIEW_KEY = "cgasi-view"

# Reuse the existing sarif-ingest convenience wrapper. This file lives at
# cga/cgasi/cgasi/cli.py, so the repository root is parents[3].
SRFI = Path(__file__).resolve().parents[3] / "sarif-ingest" / "bin" / "srfi"


def _run_srfi(args: List[str]) -> None:
    if not SRFI.is_file():
        cgast.die(f"{COMPONENT}: sarif-ingest tool not found at {SRFI}")
    proc = subprocess.run([str(SRFI), *args], text=True,
                          stdout=subprocess.PIPE)
    if proc.stdout:
        for line in proc.stdout.rstrip().splitlines():
            cgast.info(f"  {line}")
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


def _db(state: Dict[str, Any]) -> Path:
    return cgast.require_path(
        state, DB_KEY, "run 'cgasi ingest --name NAME' or 'cgasi toduck'")


def _ingestions(state: Dict[str, Any]) -> Dict[str, Any]:
    value = state.setdefault(INGESTIONS_KEY, {})
    if not isinstance(value, dict):
        cgast.die(f"{INGESTIONS_KEY!r} must be a JSON object")
    return value


def _segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return cleaned or "result"


def _sqlite_count(path: Path) -> int:
    try:
        with closing(sqlite3.connect(path)) as conn:
            row = conn.execute("select count(*) from sarif_results").fetchone()
            return int(row[0]) if row else 0
    except sqlite3.Error as exc:
        cgast.die(f"{COMPONENT}: invalid SQLite database {path}: {exc}")


def _toduck_output(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    return path if path.suffix == ".duckdb" else Path(f"{path}.duckdb")


def _print_rows(rows: List[Dict[str, Any]]) -> None:
    if not rows:
        cgast.info("(no rows)")
        return
    columns = list(rows[0])
    cgast.info("\t".join(columns))
    for row in rows:
        cgast.info("\t".join(
            "" if row.get(column) is None else str(row.get(column))
            for column in columns))


def _submission(state: Dict[str, Any], name: str) -> Dict[str, Any]:
    submissions = state.get("cgamr-submissions", {})
    if not isinstance(submissions, dict):
        cgast.die("'cgamr-submissions' must be a JSON object")
    item = submissions.get(name)
    if not isinstance(item, dict):
        cgast.die(f"{COMPONENT}: unknown MRVA submission {name!r}")
    return item


def _ingest_root(state: Dict[str, Any], output_dir: str | None) -> Path:
    if output_dir:
        root = Path(output_dir).expanduser().resolve()
    else:
        root = cgast.get_path(state, ROOT_KEY) or \
            cgast.new_tempdir(prefix="cgasi-")
    root.mkdir(parents=True, exist_ok=True)
    cgast.set_path(state, ROOT_KEY, root)
    return root


def _extract(archive: Path, destination: Path) -> None:
    try:
        with zipfile.ZipFile(archive) as source:
            data = source.read("results.sarif")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        cgast.die(f"{COMPONENT}: cannot extract results.sarif from "
                  f"{archive}: {exc}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(destination)


def _all_sqlites(ingestions: Dict[str, Any]) -> List[Path]:
    paths: List[Path] = []
    for name in sorted(ingestions):
        item = ingestions[name]
        if not isinstance(item, dict):
            continue
        jobs = item.get("jobs", [])
        if not isinstance(jobs, list) or not jobs:
            cgast.die(f"{COMPONENT}: invalid job list for {name}")
        for job in jobs:
            if not isinstance(job, dict):
                cgast.die(f"{COMPONENT}: invalid job record for {name}")
            artifacts = job.get("artifacts", {})
            value = artifacts.get("sqlite") if isinstance(artifacts, dict) \
                else None
            if not isinstance(value, str):
                cgast.die(f"{COMPONENT}: invalid SQLite path for {name}")
            path = cgast.resolve(value)
            if not path.is_file():
                cgast.die(f"{COMPONENT}: SQLite input missing for {name}: "
                          f"{path}; rerun that ingestion")
            paths.append(path)
    return paths


def _mrva_job(submission: Dict[str, Any], repository: str) -> Dict[str, Any]:
    response = submission.get("status_response", {})
    scanned = response.get("scanned_repositories", []) \
        if isinstance(response, dict) else []
    if not isinstance(scanned, list):
        return {}
    for item in scanned:
        if not isinstance(item, dict):
            continue
        repo = item.get("repository", {})
        if isinstance(repo, dict) and repo.get("full_name") == repository:
            return item
    return {}


def cmd_ingest(state: Dict[str, Any], args) -> None:
    submission = _submission(state, args.name)
    if submission.get("status") != "succeeded":
        cgast.die(f"{COMPONENT}: submission {args.name!r} has status "
                  f"{submission.get('status')!r}, not 'succeeded'")
    user = str(submission.get("user") or "")
    if not user:
        cgast.die(f"{COMPONENT}: submission {args.name!r} has no user")
    downloads = submission.get("downloads", [])
    repositories = submission.get("repositories", [])
    if not isinstance(downloads, list) or not downloads:
        cgast.die(f"{COMPONENT}: submission {args.name!r} has no downloads")
    if not isinstance(repositories, list) or len(repositories) != len(downloads):
        cgast.die(f"{COMPONENT}: submission {args.name!r} download/repository "
                  "counts do not match")

    root = _ingest_root(state, args.output_dir)
    destination = root / _segment(args.name)
    destination.mkdir(parents=True, exist_ok=True)
    jobs: List[Dict[str, Any]] = []
    rows = 0
    cgast.info(f"{COMPONENT}: ingesting {args.name} user={user} "
               f"archives={len(downloads)}")

    for index, (download, repository) in enumerate(
            zip(downloads, repositories), start=1):
        if not isinstance(download, str) or not isinstance(repository, str):
            cgast.die(f"{COMPONENT}: invalid download metadata for {args.name}")
        archive = cgast.resolve(download)
        if not archive.is_file():
            cgast.die(f"{COMPONENT}: result archive missing: {archive}")
        base = f"job-{index:02d}-{_segment(repository.replace('/', '-'))}"
        sarif = destination / f"{base}.sarif"
        sqlite = destination / f"{base}.sqlite"
        _extract(archive, sarif)
        _run_srfi(["tolite", str(sarif), str(sqlite), "--user", user])
        nrows = _sqlite_count(sqlite)
        rows += nrows
        mrva_job = _mrva_job(submission, repository)
        jobs.append({
            "repository": repository,
            "status": mrva_job.get("analysis_status",
                                   submission.get("status")),
            "finding_count": nrows,
            "mrva_result_count": mrva_job.get("result_count"),
            "artifact_size_bytes": mrva_job.get("artifact_size_in_bytes"),
            "artifacts": {
                "archive": cgast.rel(archive),
                "sarif": cgast.rel(sarif),
                "sqlite": cgast.rel(sqlite),
            },
        })
        cgast.info(f"  {repository}: {nrows} result row(s)")

    record = {
        "name": args.name,
        "user": user,
        "session_id": submission.get("session_id"),
        "language": submission.get("language"),
        "status": submission.get("status"),
        "query_pack": submission.get("pack"),
        "finding_count": rows,
        "jobs": jobs,
    }
    ingestions = _ingestions(state)
    pending = dict(ingestions)
    pending[args.name] = record
    inputs = _all_sqlites(pending)
    database = root / "all.duckdb"
    candidate = root / "all.next.duckdb"
    _run_srfi(["toduck", str(candidate), *map(str, inputs)])
    cumulative_rows = store.count(candidate)
    expected_rows = sum(
        int(item.get("finding_count", 0))
        for item in pending.values() if isinstance(item, dict))
    if cumulative_rows != expected_rows:
        cgast.die(f"{COMPONENT}: cumulative row count {cumulative_rows} does "
                  f"not match per-ingestion total {expected_rows}")

    candidate.replace(database)
    ingestions[args.name] = record
    state[ACTIVE_KEY] = args.name
    cgast.set_path(state, DB_KEY, database)
    cgast.info(f"{COMPONENT}: cumulative db -> {cgast.rel(database)} "
               f"({len(inputs)} SQLite input(s), {cumulative_rows} row(s))")


def cmd_tolite(state: Dict[str, Any], args) -> None:
    sarif = Path(args.sarif).expanduser().resolve()
    if not sarif.is_file():
        cgast.die(f"{COMPONENT} tolite: SARIF input not found: {sarif}")
    output = Path(args.output).expanduser().resolve() if args.output \
        else sarif.with_suffix(".sqlite")
    _run_srfi(["tolite", str(sarif), str(output), "--user", args.user])
    values = state.setdefault(SQLITES_KEY, [])
    if not isinstance(values, list):
        cgast.die(f"{SQLITES_KEY!r} must be a JSON array")
    relative = cgast.rel(output)
    if relative not in values:
        values.append(relative)
    cgast.info(f"{COMPONENT}: SQLite -> {relative} "
               f"({_sqlite_count(output)} row(s), user={args.user!r})")


def cmd_toduck(state: Dict[str, Any], args) -> None:
    values = args.sqlites or state.get(SQLITES_KEY, [])
    if not isinstance(values, list) or not values:
        cgast.die(f"{COMPONENT} toduck: provide SQLite inputs or run tolite")
    inputs = [cgast.resolve(value) if not Path(value).is_absolute()
              else Path(value).resolve() for value in values]
    missing = [path for path in inputs if not path.is_file()]
    if missing:
        cgast.die(f"{COMPONENT} toduck: SQLite input(s) missing: "
                  + ", ".join(map(str, missing)))
    output = _toduck_output(args.output)
    _run_srfi(["toduck", str(output), *map(str, inputs)])
    cgast.set_path(state, DB_KEY, output)
    cgast.info(f"{COMPONENT}: cumulative db -> {cgast.rel(output)} "
               f"({store.count(output)} row(s))")


def cmd_keys(state: Dict[str, Any], _args) -> None:
    for key in store.keys(_db(state)):
        cgast.info(key)


def cmd_values(state: Dict[str, Any], args) -> None:
    for value in store.distinct(_db(state), args.key):
        cgast.info(value)


def cmd_list(state: Dict[str, Any], args) -> None:
    _print_rows(store.sample(_db(state), args.n))


def cmd_search(state: Dict[str, Any], args) -> None:
    if len(args.criteria) % 2 != 0:
        cgast.die(f"{COMPONENT} search: expects [key value ...] pairs", 2)
    pairs = list(zip(args.criteria[::2], args.criteria[1::2]))
    _print_rows(store.select(_db(state), pairs))


def cmd_sql(state: Dict[str, Any], args) -> None:
    if args.query_file:
        cgast.set_path(state, QUERY_KEY, Path(args.query_file).resolve())
    query_path = cgast.require_path(
        state, QUERY_KEY,
        "pass --query-file FILE or set cgasi-query in the CGAST")
    query = query_path.read_text(encoding="utf-8").strip()
    _print_rows(store.run_sql(_db(state), query))


def cmd_info(state: Dict[str, Any], _args) -> None:
    database = cgast.get_path(state, DB_KEY)
    ingestions = state.get(INGESTIONS_KEY, {})
    count = len(ingestions) if isinstance(ingestions, dict) else 0
    users = sorted({
        str(item.get("user"))
        for item in ingestions.values()
        if isinstance(item, dict) and item.get("user")
    }) if isinstance(ingestions, dict) else []
    cgast.info(f"{COMPONENT}: cumulative SARIF result store")
    cgast.info(f"  database:    {cgast.rel(database) if database else '(none)'}")
    cgast.info(f"  ingestions:  {count}")
    cgast.info(f"  users:       {', '.join(users) or '(none)'}")
    if database:
        cgast.info(f"  results:     {store.count(database)}")
        cgast.info(f"  keys:        {', '.join(store.keys(database))}")
    cgast.info(f"  backend:     {SRFI}")


def cmd_verify(state: Dict[str, Any], args) -> None:
    ingestions = _ingestions(state)
    names = args.names or list(ingestions)
    if not names:
        cgast.die(f"{COMPONENT} verify: no ingestions")
    ok = True
    expected_rows = sum(
        int(item.get("finding_count", 0))
        for item in ingestions.values() if isinstance(item, dict))
    expected_inputs = sum(
        len(item.get("jobs", []))
        for item in ingestions.values()
        if isinstance(item, dict) and isinstance(item.get("jobs", []), list)
    )
    for name in names:
        item = ingestions.get(name)
        if not isinstance(item, dict):
            cgast.info(f"  FAIL {name}: no ingestion record")
            ok = False
            continue
        jobs = item.get("jobs", [])
        records_ok = isinstance(jobs, list) and bool(jobs) and all(
            isinstance(job, dict)
            and isinstance(job.get("artifacts"), dict)
            and all(isinstance(job["artifacts"].get(kind), str)
                    for kind in ("archive", "sarif", "sqlite"))
            and isinstance(job.get("finding_count"), int)
            for job in jobs)
        paths = [job["artifacts"][kind]
                 for job in jobs for kind in ("archive", "sarif", "sqlite")] \
            if records_ok else []
        files_ok = bool(paths) and all(cgast.resolve(path).is_file()
                                       for path in paths)
        schemas_ok = False
        row_counts_ok = records_ok and sum(
            job["finding_count"] for job in jobs) == item.get("finding_count")
        if records_ok and files_ok:
            schemas_ok = True
            for job in jobs:
                path = job["artifacts"]["sqlite"]
                with closing(sqlite3.connect(cgast.resolve(path))) as conn:
                    columns = [row[1] for row in
                               conn.execute("pragma table_info(sarif_results)")]
                    users = {
                        row[0] for row in conn.execute(
                            "select distinct user from sarif_results")
                    } if "user" in columns else set()
                schemas_ok = (schemas_ok and "user" in columns
                              and (not users or users == {item.get("user")}))
        line_ok = bool(records_ok and files_ok and schemas_ok and row_counts_ok)
        ok = ok and line_ok
        cgast.info(f"  {'PASS' if line_ok else 'FAIL'} {name}: "
                   f"user={item.get('user')} inputs="
                   f"{len(jobs) if isinstance(jobs, list) else 0} "
                   f"rows={item.get('finding_count')}")

    database = cgast.get_path(state, DB_KEY)
    db_ok = bool(database and database.is_file())
    actual_rows = -1
    if db_ok:
        try:
            db_ok = "user" in store.keys(database)
            actual_rows = store.count(database)
            db_ok = db_ok and actual_rows == expected_rows
        except store.StoreError:
            db_ok = False
    ok = ok and db_ok
    cgast.info(f"  {'PASS' if db_ok else 'FAIL'} cumulative: "
               f"inputs={expected_inputs} rows={actual_rows}/{expected_rows}")
    if not ok:
        raise SystemExit(1)
    cgast.info(f"{COMPONENT}: PASS ({len(names)} ingestion(s))")


def cmd_view(state: Dict[str, Any], args) -> None:
    view = state.setdefault(VIEW_KEY, {})
    if not isinstance(view, dict):
        cgast.die(f"{VIEW_KEY!r} must be a JSON object")
    filters = view.setdefault("filters", {})
    if not isinstance(filters, dict):
        cgast.die(f"{VIEW_KEY!r}.filters must be a JSON object")

    if args.clear:
        filters.clear()
    for label in store.FILTER_ORDER:
        value = getattr(args, label)
        if value is not None:
            if value == "":
                filters.pop(label, None)
            else:
                filters[label] = value
    if args.erc is not None:
        view["erc"] = args.erc
    view.setdefault("erc", store.DEFAULT_ERC)

    cgast.info(f"{COMPONENT}: findings view erc={view['erc']} "
               f"(choices {', '.join(map(str, store.ERC_CHOICES))})")
    for label in store.FILTER_ORDER:
        cgast.info(f"  {label}: {filters.get(label) or '(all)'}")


def cmd_serve(_state: Dict[str, Any], _args) -> None:
    import cga_http as C
    port = int(os.environ.get("CGA_CGASI_PORT", DEFAULT_PORT))
    C.serve(COMPONENT, port, serve.routes())
    raise SystemExit(0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=COMPONENT,
        description="Cumulative CGAST SARIF ingestion and query client",
    )
    sub = parser.add_subparsers(dest="cmd")

    sp = sub.add_parser("ingest", help="ingest one named cgamr submission")
    sp.add_argument("--name", required=True, help="successful downloaded MRVA submission label")
    sp.add_argument("--output-dir", default=None,
                    help="ingestion root; otherwise reuse cgasi-root or allocate a directory")
    sp.set_defaults(func=cmd_ingest)

    sp = sub.add_parser("tolite", help="convert one SARIF to SQLite")
    sp.add_argument("sarif", help="existing SARIF input file")
    sp.add_argument("output", nargs="?", default=None,
                    help="SQLite destination (default: SARIF path with .sqlite suffix)")
    sp.add_argument("--user", default="", help="user attribution on every result (default: empty)")
    sp.set_defaults(func=cmd_tolite)

    sp = sub.add_parser("toduck", help="combine SQLite inputs into DuckDB")
    sp.add_argument("output", help="DuckDB destination; .duckdb is appended if absent")
    sp.add_argument("sqlites", nargs="*", help="SQLite inputs; otherwise use cgasi-sqlites")
    sp.set_defaults(func=cmd_toduck)

    sp = sub.add_parser("keys", help="list result columns")
    sp.set_defaults(func=cmd_keys)
    sp = sub.add_parser("values", help="list distinct values of one column")
    sp.add_argument("key", help="sarif_results column name (see keys)")
    sp.set_defaults(func=cmd_values)
    sp = sub.add_parser("list", help="list the first N results")
    sp.add_argument("n", nargs="?", type=int, default=20,
                    help="maximum result rows to display (default: 20)")
    sp.set_defaults(func=cmd_list)
    sp = sub.add_parser("search", help="exact-match result search")
    sp.add_argument("criteria", nargs="*", metavar="key value",
                    help="exact-match column/value pairs; omitted means all results")
    sp.set_defaults(func=cmd_search)
    sp = sub.add_parser("sql", help="run read-only SQL from cgasi-query")
    sp.add_argument("--query-file", default=None, help="SQL file recorded as cgasi-query")
    sp.set_defaults(func=cmd_sql)
    sp = sub.add_parser("info", help="show cumulative-store information")
    sp.set_defaults(func=cmd_info)
    sp = sub.add_parser(
        "view", help="set the Findings view (ERC + per-column regex filters)")
    sp.add_argument("--erc", type=int, choices=store.ERC_CHOICES, default=None,
                    help="entry row count shown in the Findings table")
    for label in store.FILTER_ORDER:
        sp.add_argument(f"--{label}", default=None, metavar="REGEX",
                        help=f"regex filter for the {label} column "
                             "('' clears it)")
    sp.add_argument("--clear", action="store_true",
                    help="clear every column filter before applying options")
    sp.set_defaults(func=cmd_view)
    sp = sub.add_parser("verify", help="verify ingestions and cumulative DB")
    sp.add_argument("names", nargs="*", help="ingestion labels; omitted means all")
    sp.set_defaults(func=cmd_verify)
    sp = sub.add_parser("serve", help="serve live result fragments")
    sp.set_defaults(func=cmd_serve)
    return enhance_parser(parser, "si")


def main(argv: List[str]) -> int:
    parser = build_parser()
    if not argv or argv[0] in ("-h", "--help", "help"):
        parser.print_help(sys.stderr)
        return 0
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help(sys.stderr)
        return 0
    state = cgast.read()
    try:
        args.func(state, args)
    except (OSError, sqlite3.Error, store.StoreError) as exc:
        cgast.die(f"{COMPONENT}: {exc}")
    cgast.write(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
