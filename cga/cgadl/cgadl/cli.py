"""cgadl command-line interface (DB library handler) -- CGAST edition.

Every cgadl command is a JSON-in/JSON-out filter (see cgalib/cgast.py): it reads
the CGAST from stdin, does its work, and writes the (merged) CGAST to stdout.
All human output goes to stderr. State is passed between commands as CGAST keys
pointing at anonymous temp files under cga-tmp/ -- there are no default paths.

    cgadl getmeta <url|path>          # fetch metadata.sql   -> cgadl-metadata
    cgadl keys       [--metadata P]   # catalogue keys
    cgadl values <key> [--metadata P] # distinct values of one key
    cgadl list [N]   [--metadata P]   # list the first N databases
    cgadl select [key value ...]      # exact-match select   -> cgadl-selection
    cgadl sql                         # read SQL from cgadl-query -> cgadl-selection
    cgadl download                    # fetch selected DBs   -> cgadl-dbdir
    cgadl info       [--metadata P]   # high-level info
    cgadl serve                       # serve fragments from the session CGAST

CGAST keys: cgadl-metadata (catalogue), cgadl-query (SQL text file),
cgadl-selection (active selected-for-download JSON), cgadl-dbdir (active
download directory), and cgadl-history (user-scoped selection history).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import cgast
from command_help import enhance_parser
from workflow import WorkflowError

from . import catalog, download, selection

COMPONENT = "cgadl"
DEFAULT_PORT = 8602

META_KEY = "cgadl-metadata"
QUERY_KEY = "cgadl-query"
SELECTION_KEY = "cgadl-selection"
DBDIR_KEY = "cgadl-dbdir"
HISTORY_KEY = "cgadl-history"


# --- helpers ---------------------------------------------------------------
def _metadata(cgast_obj: Dict[str, Any], args) -> Path:
    """Resolve the catalogue path from --metadata (recorded) or the CGAST."""
    if getattr(args, "metadata", None):
        cgast.set_path(cgast_obj, META_KEY, Path(args.metadata).resolve())
    return cgast.require_path(
        cgast_obj, META_KEY,
        "pass --metadata <metadata.sql> or run 'cgadl getmeta' first")


def _print_rows(rows) -> None:
    if not rows:
        cgast.info("(no matching databases)")
        return
    header = (f"{'owner':<20} {'repo':<24} {'lang':<10} "
              f"{'tool_ver':<10} {'size_MB':>9}  result_url")
    cgast.info(header)
    cgast.info("-" * len(header))
    for r in rows:
        size = r["db_file_size"]
        size_mb = f"{size / (1024 * 1024):.1f}" if size else "?"
        cgast.info(f"{str(r['git_owner']):<20} {str(r['git_repo']):<24} "
                   f"{str(r['primary_language']):<10} "
                   f"{str(r['tool_version']):<10} {size_mb:>9}  "
                   f"{r['result_url']}")


def _print_raw(rows) -> None:
    if not rows:
        cgast.info("(no rows)")
        return
    cols = list(rows[0].keys())
    cgast.info("\t".join(cols))
    for r in rows:
        cgast.info("\t".join("" if r[c] is None else str(r[c]) for c in cols))


def _history(cgast_obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    history = cgast_obj.setdefault(HISTORY_KEY, [])
    if not isinstance(history, list):
        cgast.die(f"{COMPONENT}: {HISTORY_KEY} must be an array", 2)
    return history


def _write_selection(cgast_obj: Dict[str, Any], rows,
                     user: str | None = None) -> None:
    dicts = [catalog.row_to_dict(r) for r in rows]
    out = cgast.new_tempfile(suffix=".json")
    selection.write_selection(out, dicts)
    cgast.set_path(cgast_obj, SELECTION_KEY, out)
    _history(cgast_obj).append({
        "user": user or "",
        "selection": cgast.rel(out),
    })
    cgast.info(f"{COMPONENT}: selected {len(dicts)} database(s) -> "
               f"{cgast.rel(out)}")


# --- commands --------------------------------------------------------------
def cmd_getmeta(cgast_obj, args) -> None:
    src = args.url
    out = cgast.new_tempfile(suffix=".sql")
    local = Path(src).expanduser()
    if local.exists():
        out.write_bytes(local.read_bytes())
    else:
        download.getmeta_url(src, out)
    cgast.set_path(cgast_obj, META_KEY, out)
    cgast.info(f"{COMPONENT}: metadata -> {cgast.rel(out)}")


def cmd_keys(cgast_obj, args) -> None:
    conn = catalog.connect(_metadata(cgast_obj, args))
    try:
        for k in catalog.keys(conn):
            cgast.info(k)
    finally:
        conn.close()


def cmd_values(cgast_obj, args) -> None:
    conn = catalog.connect(_metadata(cgast_obj, args))
    try:
        for v in catalog.distinct(conn, args.key):
            cgast.info(v)
    finally:
        conn.close()


def cmd_list(cgast_obj, args) -> None:
    conn = catalog.connect(_metadata(cgast_obj, args))
    try:
        _print_rows(catalog.sample(conn, args.n))
    finally:
        conn.close()


def cmd_select(cgast_obj, args) -> None:
    if len(args.criteria) % 2 != 0:
        cgast.die(f"{COMPONENT} select: expects [key value ...] pairs", 2)
    pairs = list(zip(args.criteria[::2], args.criteria[1::2]))
    conn = catalog.connect(_metadata(cgast_obj, args))
    try:
        rows = catalog.select(conn, pairs)
    finally:
        conn.close()
    _print_rows(rows)
    _write_selection(cgast_obj, rows, getattr(args, "user", None))


def cmd_sql(cgast_obj, args) -> None:
    if getattr(args, "query_file", None):
        cgast.set_path(cgast_obj, QUERY_KEY, Path(args.query_file).resolve())
    qpath = cgast.require_path(
        cgast_obj, QUERY_KEY,
        "pass --query-file <file.sql> or set cgadl-query in the CGAST")
    query = qpath.read_text(encoding="utf-8").strip()
    if not query:
        cgast.die(f"{COMPONENT} sql: query file {qpath} is empty", 2)
    conn = catalog.connect(_metadata(cgast_obj, args))
    try:
        rows = catalog.run_sql(conn, query)
    finally:
        conn.close()
    if rows and "result_url" in rows[0].keys():
        _print_rows(rows)
        _write_selection(cgast_obj, rows, getattr(args, "user", None))
    else:
        _print_raw(rows)


def cmd_download(cgast_obj, args) -> None:
    sel = cgast.require_path(cgast_obj, SELECTION_KEY,
                            "run 'cgadl select ...' first")
    rows = selection.read_selection(sel)
    if not rows:
        cgast.die(f"{COMPONENT} download: empty selection {cgast.rel(sel)}")
    if args.output_dir:
        dbdir = Path(args.output_dir).expanduser().resolve()
        dbdir.mkdir(parents=True, exist_ok=True)
    else:
        dbdir = cgast.new_tempdir()

    completed = 0

    def report(res: download.DownloadResult) -> None:
        nonlocal completed
        completed += 1
        tag = res.status.upper()
        extra = res.error if res.status == "error" \
            else (f"{res.size} bytes" if res.size else "")
        cgast.info(f"  [{completed}/{len(rows)}] {tag:<10} "
                   f"{res.owner}/{res.repo} -> {res.dest} {extra}")

    def report_bytes(owner: str, repo: str, received: int, total: int | None) -> None:
        amount = f"{received / 1024**2:.1f} MiB"
        if total is not None:
            amount += f" / {total / 1024**2:.1f} MiB"
            if total:
                amount += f" ({100 * received / total:.0f}%)"
        cgast.info(f"  [{completed + 1}/{len(rows)}] DOWNLOADING "
                   f"{owner}/{repo}: {amount}")

    cgast.info(f"{COMPONENT}: downloading {len(rows)} database(s) into "
               f"{cgast.rel(dbdir)}")
    results = download.download(rows, dbdir, force=args.force,
                                dry_run=args.dry_run, progress=report,
                                transfer_progress=report_bytes)
    ok = sum(1 for r in results if r.status in ("downloaded", "skipped"))
    errs = sum(1 for r in results if r.status == "error")
    cgast.set_path(cgast_obj, DBDIR_KEY, dbdir)
    active = cgast_obj.get(SELECTION_KEY)
    for item in reversed(_history(cgast_obj)):
        if isinstance(item, dict) and item.get("selection") == active:
            item["dbdir"] = cgast.rel(dbdir)
            break
    cgast.info(f"{COMPONENT}: {ok} ready, {errs} error(s)")
    if errs:
        raise SystemExit(1)


def cmd_info(cgast_obj, args) -> None:
    cgast.info(f"{COMPONENT}: CodeQL DB library handler")
    meta = cgast.get_path(cgast_obj, META_KEY)
    if getattr(args, "metadata", None):
        meta = Path(args.metadata).resolve()
        cgast.set_path(cgast_obj, META_KEY, meta)
    if meta is None:
        cgast.info("  catalogue:  (none in CGAST; pass --metadata or getmeta)")
    else:
        try:
            conn = catalog.connect(meta)
            try:
                cgast.info(f"  catalogue:  {cgast.rel(meta)}")
                cgast.info(f"  databases:  {catalog.count(conn)}")
                cgast.info(f"  keys:       {', '.join(catalog.keys(conn))}")
            finally:
                conn.close()
        except (catalog.CatalogError, WorkflowError) as exc:
            cgast.info(f"  catalogue:  {cgast.rel(meta)}")
            cgast.info(f"  error:      {exc}")
    sel = cgast.get_path(cgast_obj, SELECTION_KEY)
    n_sel = len(selection.read_selection(sel)) if sel else 0
    cgast.info(f"  selection:  {cgast.rel(sel) if sel else '(none)'} "
               f"({n_sel} selected)")
    dbdir = cgast.get_path(cgast_obj, DBDIR_KEY)
    cgast.info(f"  dbdir:      {cgast.rel(dbdir) if dbdir else '(none)'}")


def cmd_serve(_cgast_obj, _args) -> None:
    import cga_http as C  # provided on sys.path by bin/cgadl
    from . import serve as serve_mod
    port = int(os.environ.get("CGA_CGADL_PORT", DEFAULT_PORT))
    C.serve(COMPONENT, port, serve_mod.routes())
    raise SystemExit(0)  # serve never returns normally


# --- parser ----------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=COMPONENT,
        description="CodeQL generic appliance: DB library handler (CGAST).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd")

    def add_meta(sp):
        sp.add_argument("--metadata", default=None,
                        help="catalogue path (recorded as cgadl-metadata)")

    sp = sub.add_parser("getmeta", help="fetch metadata.sql from a URL or path")
    sp.add_argument("url", help="prepared SQLite metadata catalogue URL or local path")
    sp.set_defaults(func=cmd_getmeta)

    sp = sub.add_parser("keys", help="list catalogue keys")
    add_meta(sp)
    sp.set_defaults(func=cmd_keys)

    sp = sub.add_parser("values", help="distinct values of one key")
    sp.add_argument("key", help="catalogue column name (see keys)")
    add_meta(sp)
    sp.set_defaults(func=cmd_values)

    sp = sub.add_parser("list", help="list the first N databases")
    sp.add_argument("n", nargs="?", type=int, default=10,
                    help="maximum rows to display (default: 10)")
    add_meta(sp)
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("select", help="write a selection (exact match)")
    sp.add_argument("criteria", nargs="*", metavar="key value",
                    help="exact-match column/value pairs; omitted means all rows")
    sp.add_argument("--user", default=None,
                    help="attribute this selection to a user")
    add_meta(sp)
    sp.set_defaults(func=cmd_select)

    sp = sub.add_parser("sql", help="run read-only SQL from cgadl-query")
    sp.add_argument("--query-file", default=None,
                    help="SQL file (recorded as cgadl-query)")
    sp.add_argument("--user", default=None,
                    help="attribute this selection to a user")
    add_meta(sp)
    sp.set_defaults(func=cmd_sql)

    sp = sub.add_parser("download", help="download the selected databases")
    sp.add_argument("--output-dir", default=None,
                    help="explicit qldbstore destination (recorded in CGAST)")
    sp.add_argument("--force", action="store_true",
                    help="re-download even if the destination exists")
    sp.add_argument("--dry-run", action="store_true",
                    help="print planned destinations without downloading")
    sp.set_defaults(func=cmd_download)

    sp = sub.add_parser("info", help="high-level info")
    add_meta(sp)
    sp.set_defaults(func=cmd_info)

    sp = sub.add_parser("serve", help="serve fragments from the session CGAST")
    sp.set_defaults(func=cmd_serve)

    return enhance_parser(p, "dl")


def main(argv: List[str]) -> int:
    parser = build_parser()
    if not argv or argv[0] in ("-h", "--help", "help"):
        parser.print_help(sys.stderr)
        return 0
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help(sys.stderr)
        return 0
    cgast_obj = cgast.read()
    try:
        args.func(cgast_obj, args)
    except catalog.CatalogError as exc:
        cgast.die(f"{COMPONENT}: {exc}")
    cgast.write(cgast_obj)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
