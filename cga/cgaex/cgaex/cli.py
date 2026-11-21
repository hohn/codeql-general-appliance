"""CGAST-native human and LLM exports from the cumulative SARIF store."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import cgast
from command_help import enhance_parser
from cgasi import store

from . import export, serve

COMPONENT = "cgaex"
DEFAULT_PORT = 8608
EXPORTS_KEY = "cgaex-exports"


def _findings(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    database = cgast.require_path(
        state, "cgasi-db", "run 'cgasi ingest' before exporting results")
    return store.run_sql(
        database,
        "select user, file_name, kind, rule_id, rule_name, uri, "
        "start_line, start_column from sarif_results "
        "order by user, file_name, uri, start_line, start_column",
    )


def _destination(args, suffix: str) -> Path:
    if args.output:
        return Path(args.output).expanduser().resolve()
    return cgast.new_tempfile(prefix="cgaex-", suffix=suffix)


def _record(state: Dict[str, Any], name: str, path: Path, count: int) -> None:
    values = state.setdefault(EXPORTS_KEY, {})
    if not isinstance(values, dict):
        cgast.die(f"{EXPORTS_KEY!r} must be a JSON object")
    values[name] = {
        "path": cgast.rel(path),
        "finding_count": count,
    }
    state["cgaex-active"] = name
    state["cgaex-finding-count"] = count


def cmd_human(state: Dict[str, Any], args) -> None:
    findings = _findings(state)
    output = _destination(args, ".md")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(export.render_human(state, findings), encoding="utf-8")
    _record(state, "human", output, len(findings))
    cgast.info(f"{COMPONENT}: human export -> {cgast.rel(output)} "
               f"({len(findings)} finding(s))")


def cmd_llm(state: Dict[str, Any], args) -> None:
    findings = _findings(state)
    output = _destination(args, ".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(export.render_llm(state, findings), encoding="utf-8")
    _record(state, "llm", output, len(findings))
    cgast.info(f"{COMPONENT}: LLM export -> {cgast.rel(output)} "
               f"({len(findings)} finding(s))")


def cmd_info(state: Dict[str, Any], _args) -> None:
    exports = state.get(EXPORTS_KEY, {})
    cgast.info(f"{COMPONENT}: result exporter")
    if not isinstance(exports, dict) or not exports:
        cgast.info("  (no exports)")
        return
    for name, item in sorted(exports.items()):
        if isinstance(item, dict):
            cgast.info(f"  {name}: {item.get('path')} "
                       f"({item.get('finding_count', 0)} finding(s))")


def cmd_serve(_state: Dict[str, Any], _args) -> None:
    import cga_http as C
    port = int(os.environ.get("CGA_CGAEX_PORT", DEFAULT_PORT))
    C.serve(COMPONENT, port, serve.routes())
    raise SystemExit(0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=COMPONENT,
        description="CodeQL generic appliance: result exporter (CGAST).",
    )
    sub = parser.add_subparsers(dest="cmd")
    for name, func, help_text in (
        ("human", cmd_human, "write a human-readable Markdown report"),
        ("llm", cmd_llm, "write a structured JSON document for LLM use"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--output", default=None,
                             help="report destination (overwritten); otherwise allocate a managed file")
        command.set_defaults(func=func)
    command = sub.add_parser("info", help="show generated exports")
    command.set_defaults(func=cmd_info)
    command = sub.add_parser("serve", help="serve live export fragments")
    command.set_defaults(func=cmd_serve)
    return enhance_parser(parser, "ex")


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
    except (store.StoreError, export.ExportError) as exc:
        cgast.die(f"{COMPONENT}: {exc}")
    cgast.write(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
