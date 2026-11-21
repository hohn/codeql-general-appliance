"""cgaql command-line interface (query library handler) -- CGAST edition.

Every cgaql command is a JSON-in/JSON-out filter (see cgalib/cgast.py): it reads
the CGAST from stdin, does its work, and writes the merged CGAST to stdout. All
human output goes to stderr. State is passed as CGAST keys pointing at anonymous
temp files under cga-tmp/ -- there are no default paths.

    cgaql index <querydir>      # scan .ql tree -> SQLite index (cgaql-index)
    cgaql keys                  # catalogue keys
    cgaql values <key>          # distinct values of one key
    cgaql list [N]              # list the first N queries
    cgaql select [key value ...]# exact-match select -> cgaql-selection
    cgaql sql                   # read SQL from cgaql-query -> cgaql-selection
    cgaql pack                  # bundle selected queries -> cgaql-pack (array)
    cgaql clean                 # remove the cgaql-pack bundles
    cgaql info                  # high-level info
    cgaql serve                 # serve fragments from the session CGAST

CGAST keys: cgaql-querydir (.ql source), cgaql-index (SQLite catalogue),
cgaql-query (SQL text file), cgaql-selection (active selected queries JSON),
cgaql-pack (active JSON array of pack-bundle temp files), and cgaql-history
(user-scoped selection history).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import cgast
from command_help import enhance_parser

from . import catalog, pack, selection

COMPONENT = "cgaql"
DEFAULT_PORT = 8603

QUERYDIR_KEY = "cgaql-querydir"
INDEX_KEY = "cgaql-index"
QUERY_KEY = "cgaql-query"
SELECTION_KEY = "cgaql-selection"
PACK_KEY = "cgaql-pack"
HISTORY_KEY = "cgaql-history"


def _codeql_binary() -> str:
    return os.environ.get("CGA_CGAQL_CODEQL", "codeql")


def _index(cgast_obj: Dict[str, Any]) -> "catalog.sqlite3.Connection":
    idx = cgast.require_path(cgast_obj, INDEX_KEY, "run 'cgaql index <dir>' first")
    return catalog.connect(idx)


def _print_rows(rows) -> None:
    if not rows:
        cgast.info("(no matching queries)")
        return
    header = (f"{'language':<12} {'id':<28} {'kind':<14} "
              f"{'severity':<14} {'relpath'}")
    cgast.info(header)
    cgast.info("-" * len(header))
    for r in rows:
        cgast.info(f"{str(r['language']):<12} {str(r['id']):<28} "
                   f"{str(r['kind']):<14} {str(r['severity']):<14} "
                   f"{r['relpath']}")


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
    cgast.info(f"{COMPONENT}: selected {len(dicts)} query(ies) -> "
               f"{cgast.rel(out)}")


# --- commands --------------------------------------------------------------
def cmd_index(cgast_obj, args) -> None:
    if args.querydir:
        cgast.set_path(cgast_obj, QUERYDIR_KEY, Path(args.querydir).resolve())
    querydir = cgast.require_path(
        cgast_obj, QUERYDIR_KEY,
        "pass the .ql source directory or set cgaql-querydir in the CGAST")
    index = cgast.new_tempfile(suffix=".sql")
    n = catalog.build_index(querydir, index)
    cgast.set_path(cgast_obj, INDEX_KEY, index)
    cgast.info(f"{COMPONENT}: indexed {n} query(ies) from "
               f"{cgast.rel(querydir)} -> {cgast.rel(index)}")


def cmd_keys(cgast_obj, _args) -> None:
    conn = _index(cgast_obj)
    try:
        for k in catalog.keys(conn):
            cgast.info(k)
    finally:
        conn.close()


def cmd_values(cgast_obj, args) -> None:
    conn = _index(cgast_obj)
    try:
        for v in catalog.distinct(conn, args.key):
            cgast.info(v)
    finally:
        conn.close()


def cmd_list(cgast_obj, args) -> None:
    conn = _index(cgast_obj)
    try:
        _print_rows(catalog.sample(conn, args.n))
    finally:
        conn.close()


def cmd_select(cgast_obj, args) -> None:
    if len(args.criteria) % 2 != 0:
        cgast.die(f"{COMPONENT} select: expects [key value ...] pairs", 2)
    pairs = list(zip(args.criteria[::2], args.criteria[1::2]))
    conn = _index(cgast_obj)
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
        "pass --query-file <file.sql> or set cgaql-query in the CGAST")
    query = qpath.read_text(encoding="utf-8").strip()
    if not query:
        cgast.die(f"{COMPONENT} sql: query file {qpath} is empty", 2)
    conn = _index(cgast_obj)
    try:
        rows = catalog.run_sql(conn, query)
    finally:
        conn.close()
    if rows and "path" in rows[0].keys():
        _print_rows(rows)
        _write_selection(cgast_obj, rows, getattr(args, "user", None))
    else:
        _print_raw(rows)


def cmd_pack(cgast_obj, args) -> None:
    sel = cgast.require_path(cgast_obj, SELECTION_KEY,
                            "run 'cgaql select ...' first")
    rows = selection.read_selection(sel)
    if not rows:
        cgast.die(f"{COMPONENT} pack: empty selection {cgast.rel(sel)}")
    output = getattr(args, "output", None)
    if output and len(rows) != 1:
        cgast.die("cgaql pack: --output requires exactly one selected query", 2)
    codeql = _codeql_binary()
    cgast.info(f"{COMPONENT}: packing {len(rows)} query(ies)")
    paths: List[str] = []
    errors = 0
    for i, row in enumerate(rows, start=1):
        qid = row.get("id") or row.get("relpath", "")
        language = row.get("language", "")
        source = row.get("path") or row.get("relpath", "")
        if args.dry_run:
            cgast.info(f"  PLANNED    [{language}] {qid} ({source})")
            continue
        try:
            data = pack.build_query_pack(Path(source), language, codeql)
            dest = Path(output).resolve() if output else cgast.new_tempfile(suffix=".tgz")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            paths.append(cgast.rel(dest))
            cgast.info(f"  PACKED     [{language}] {qid} -> {cgast.rel(dest)} "
                       f"({len(data)} bytes)")
        except (pack.PackError, OSError) as exc:
            errors += 1
            cgast.info(f"  ERROR      [{language}] {qid}: {exc}")
    if not args.dry_run:
        cgast_obj[PACK_KEY] = paths
        active = cgast_obj.get(SELECTION_KEY)
        for item in reversed(_history(cgast_obj)):
            if isinstance(item, dict) and item.get("selection") == active:
                item["packs"] = list(paths)
                break
        cgast.info(f"{COMPONENT}: {len(paths)} packed, {errors} error(s) -> "
                   f"{PACK_KEY}[{len(paths)}]")
    if errors:
        raise SystemExit(1)


def cmd_clean(cgast_obj, _args) -> None:
    paths = cgast_obj.get(PACK_KEY, [])
    if not isinstance(paths, list):
        paths = []
    all_paths = list(paths)
    history = _history(cgast_obj)
    for item in history:
        if not isinstance(item, dict):
            continue
        cached = item.pop("packs", [])
        if isinstance(cached, list):
            all_paths.extend(cached)
    removed = 0
    for rel_path in dict.fromkeys(all_paths):
        if not isinstance(rel_path, str):
            continue
        p = cgast.resolve(rel_path)
        if p.exists():
            p.unlink()
            removed += 1
    cgast_obj.pop(PACK_KEY, None)
    cgast.info(f"{COMPONENT}: removed {removed} pack bundle(s)")


def cmd_info(cgast_obj, _args) -> None:
    cgast.info(f"{COMPONENT}: CodeQL query library handler")
    qdir = cgast.get_path(cgast_obj, QUERYDIR_KEY)
    cgast.info(f"  source:     {cgast.rel(qdir) if qdir else '(none)'}")
    index = cgast.get_path(cgast_obj, INDEX_KEY)
    if index is None:
        cgast.info("  index:      (none in CGAST; run 'cgaql index <dir>')")
    else:
        try:
            conn = catalog.connect(index)
            try:
                cgast.info(f"  index:      {cgast.rel(index)}")
                cgast.info(f"  queries:    {catalog.count(conn)}")
                cgast.info(f"  keys:       {', '.join(catalog.keys(conn))}")
            finally:
                conn.close()
        except catalog.CatalogError as exc:
            cgast.info(f"  index:      {cgast.rel(index)}")
            cgast.info(f"  error:      {exc}")
    sel = cgast.get_path(cgast_obj, SELECTION_KEY)
    n_sel = len(selection.read_selection(sel)) if sel else 0
    cgast.info(f"  selection:  {cgast.rel(sel) if sel else '(none)'} "
               f"({n_sel} selected)")
    packs = cgast_obj.get(PACK_KEY, [])
    cgast.info(f"  packs:      {len(packs) if isinstance(packs, list) else 0} "
               f"cached")


def cmd_serve(_cgast_obj, _args) -> None:
    import cga_http as C  # provided on sys.path by bin/cgaql
    from . import serve as serve_mod
    port = int(os.environ.get("CGA_CGAQL_PORT", DEFAULT_PORT))
    C.serve(COMPONENT, port, serve_mod.routes())
    raise SystemExit(0)


# --- parser ----------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=COMPONENT,
        description="CodeQL generic appliance: query library handler (CGAST).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("index", help="scan a .ql source tree into the index")
    sp.add_argument("querydir", nargs="?", default=None,
                    help="query source directory (recorded as cgaql-querydir)")
    sp.set_defaults(func=cmd_index)

    sp = sub.add_parser("keys", help="list catalogue keys")
    sp.set_defaults(func=cmd_keys)

    sp = sub.add_parser("values", help="distinct values of one key")
    sp.add_argument("key", help="query catalogue column name (see keys)")
    sp.set_defaults(func=cmd_values)

    sp = sub.add_parser("list", help="list the first N queries")
    sp.add_argument("n", nargs="?", type=int, default=10,
                    help="maximum rows to display (default: 10)")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("select", help="write a selection (exact match)")
    sp.add_argument("criteria", nargs="*", metavar="key value",
                    help="exact-match column/value pairs; omitted means all queries")
    sp.add_argument("--user", default=None,
                    help="attribute this selection to a user")
    sp.set_defaults(func=cmd_select)

    sp = sub.add_parser("sql", help="run read-only SQL from cgaql-query")
    sp.add_argument("--query-file", default=None,
                    help="SQL file (recorded as cgaql-query)")
    sp.add_argument("--user", default=None,
                    help="attribute this selection to a user")
    sp.set_defaults(func=cmd_sql)

    sp = sub.add_parser("pack", help="bundle every selected query")
    sp.add_argument("--output", help="bundle destination for one selected query")
    sp.add_argument("--dry-run", action="store_true",
                    help="print planned packs without building")
    sp.set_defaults(func=cmd_pack)

    sp = sub.add_parser("clean", help="remove the cgaql-pack bundles")
    sp.set_defaults(func=cmd_clean)

    sp = sub.add_parser("info", help="high-level info")
    sp.set_defaults(func=cmd_info)

    sp = sub.add_parser("serve", help="serve fragments from the session CGAST")
    sp.set_defaults(func=cmd_serve)

    return enhance_parser(p, "ql")


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
