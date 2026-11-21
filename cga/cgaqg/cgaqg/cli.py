"""Materialize selected CVE query definitions into the cgaql library format."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import cgast
import workflow
from command_help import enhance_parser
from cgaql import catalog as qcatalog

COMPONENT = "cgaqg"
DEFAULT_PORT = 8504
MATERIALIZED_KEY = "cgaqg-materialized"
QUERYDIR_KEY = "cgaqg-querydir"
INDEX_KEY = "cgaqg-index"
HISTORY_KEY = "cgaqg-history"


def _query_defs(state) -> list[dict]:
    source = cgast.get_path(state, "cgacv-work-items")
    key = "items"
    if source is None:
        source = cgast.require_path(
            state, "cgacv-selection",
            "run 'cgacv select' or 'cgacv expand' first")
        key = "cves"
    doc = workflow.load_json(source)
    found = []
    seen = {}
    for parent in doc.get(key, []):
        for query in parent.get("queries", []):
            qid = query.get("id")
            signature = (query.get("path"), query.get("source"),
                         query.get("filename"), query.get("name"))
            if qid in seen and seen[qid] != signature:
                raise workflow.WorkflowError(
                    f"conflicting definitions for query {qid!r}")
            if qid not in seen:
                seen[qid] = signature
                found.append(query)
    if not found:
        raise workflow.WorkflowError(
            "selected CVE specifications contain no query definitions")
    return found


def cmd_materialize(state, args) -> None:
    queries = _query_defs(state)
    root = (Path(args.output_dir).expanduser().resolve() if args.output_dir
            else cgast.new_tempdir(prefix="cgaqg-queries."))
    root.mkdir(parents=True, exist_ok=True)
    records = []
    for query in queries:
        filename = workflow.require_safe_name(query.get("filename"),
                                              "query filename")
        if not filename.endswith(".ql"):
            raise workflow.WorkflowError(
                f"query filename must end in .ql: {filename}")
        destination = workflow.under(root, filename)
        if "path" in query:
            source = cgast.resolve(query["path"])
            if not source.is_file():
                raise workflow.WorkflowError(f"query source not found: {source}")
            text = source.read_text(encoding="utf-8")
            for support in sorted(source.parent.glob("*.qll")):
                support_destination = workflow.under(root, support.name)
                support_text = support.read_text(encoding="utf-8")
                if support_destination.exists() and \
                        support_destination.read_text(encoding="utf-8") != support_text:
                    raise workflow.WorkflowError(
                        f"conflicting query support module: {support.name}")
                support_destination.write_text(
                    support_text.rstrip() + "\n", encoding="utf-8")
        elif "source" in query:
            text = query["source"]
        else:
            raise workflow.WorkflowError(
                f"query {query.get('id')!r} has neither path nor source")
        destination.write_text(text.rstrip() + "\n", encoding="utf-8")
        records.append({**query, "materialized_path": cgast.rel(destination)})
    manifest = cgast.new_tempfile(prefix="cgaqg-materialized.", suffix=".json")
    workflow.write_json(manifest, {"version": 1, "count": len(records),
                                   "querydir": cgast.rel(root),
                                   "queries": records})
    cgast.set_path(state, MATERIALIZED_KEY, manifest)
    cgast.set_path(state, QUERYDIR_KEY, root)
    state.setdefault(HISTORY_KEY, []).append(
        {"materialized": cgast.rel(manifest), "count": len(records)})
    cgast.info(f"{COMPONENT}: materialized {len(records)} query(ies) -> "
               f"{cgast.rel(root)}")


def cmd_index(state, _args) -> None:
    root = cgast.require_path(
        state, QUERYDIR_KEY, "run 'cgaqg materialize' first")
    index = cgast.new_tempfile(prefix="cgaqg-index.", suffix=".sql")
    count = qcatalog.build_index(root, index)
    if count == 0:
        raise workflow.WorkflowError(f"no .ql queries found under {root}")
    cgast.set_path(state, INDEX_KEY, index)
    state.setdefault(HISTORY_KEY, []).append({
        "index": cgast.rel(index), "count": count})
    cgast.info(f"{COMPONENT}: indexed {count} query(ies) -> "
               f"{cgast.rel(index)}")


def cmd_info(state, _args) -> None:
    cgast.info(f"{COMPONENT}: CVE query materializer")
    for key in (MATERIALIZED_KEY, QUERYDIR_KEY, INDEX_KEY):
        path = cgast.get_path(state, key)
        cgast.info(f"  {key}: {cgast.rel(path) if path else '(none)'}")


def cmd_serve(_state, _args) -> None:
    import cga_http as C
    from . import serve
    C.serve(COMPONENT, int(os.environ.get("CGA_PREP_CGAQG_PORT", DEFAULT_PORT)),
            serve.routes())
    raise SystemExit(0)


def build_parser():
    parser = argparse.ArgumentParser(prog=COMPONENT)
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("materialize"); p.add_argument("--output-dir")
    p.set_defaults(func=cmd_materialize)
    p = sub.add_parser("index"); p.set_defaults(func=cmd_index)
    p = sub.add_parser("info"); p.set_defaults(func=cmd_info)
    p = sub.add_parser("serve"); p.set_defaults(func=cmd_serve)
    return enhance_parser(parser, "qg")


def main(argv: list[str]) -> int:
    parser = build_parser()
    if not argv or argv[0] in ("help", "-h", "--help"):
        parser.print_help(sys.stderr); return 0
    args = parser.parse_args(argv)
    state = cgast.read()
    try:
        args.func(state, args)
    except (workflow.WorkflowError, qcatalog.CatalogError) as exc:
        cgast.die(f"{COMPONENT}: {exc}", 2)
    cgast.write(state)
    return 0
