"""Read-only assistant context from CGA state, without a running web service."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlencode

COLLECTION = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(COLLECTION / name) for name in ("cgawf", "cgauv", "cgabench")]

from cgawf.repository import Repository, WorkflowError as RepositoryError
from command_help import enhance_parser
from workflow import WorkflowError, load_json


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer in 1..65535") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be in 1..65535")
    return port


def _options(parser: argparse.ArgumentParser, scope: str) -> None:
    parser.set_defaults(scope=scope)
    projections = parser.add_mutually_exclusive_group()
    projections.add_argument("--show-html-endpoint", action="store_true",
                             help="print the HTML view URL instead of context")
    projections.add_argument("--show-json-endpoint", action="store_true",
                             help="print the JSON state URL instead of context")
    projections.add_argument("--show-docs", action="store_true",
                             help="print local documentation paths instead of context")
    projections.add_argument("--json", action="store_true",
                             help="print the existing structured state projection")
    parser.add_argument("--port", type=_port,
                        help="viewer port for endpoint URLs only (does not start a server)")
    if scope == "bench":
        parser.add_argument("--session-file",
                            help="read a CGAST file outside an initialized workflow")
    else:
        parser.add_argument("--detail", choices=("summary", "steps"), default="steps")
        parser.add_argument("--include-sensitive", action="store_true",
                            help="include secret-tagged entities (redacted by default)")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="cga llm", description=__doc__)
    commands = root.add_subparsers(dest="command")
    context = commands.add_parser(
        "context", help="inspect Bench or Unified View context from local CGA state",
        description="Choose a context source; no HTTP service is required.",
        epilog="Each source supports --show-html-endpoint, --show-json-endpoint, "
               "--show-docs, and --json. Aliases: cga llm cb; cga llm cu.")
    sources = context.add_subparsers(dest="source")
    for scope, alias, description in (
        ("bench", "cb", "experiment, sessions, and D/Q/J/R state"),
        ("unified", "cu", "workflow, command history, and selected resources"),
    ):
        _options(sources.add_parser(scope, help=description), scope)
        _options(commands.add_parser(alias, help=f"alias for context {scope}"), scope)
    root.set_defaults(context_parser=context)
    return enhance_parser(root, "llm")


def _endpoint(args: argparse.Namespace) -> str:
    port = args.port
    if port is None:
        port = _port(os.environ.get("CGA_CGAUV_PORT", "8609")) \
            if args.scope == "unified" else 8610
    path = "/"
    if args.show_json_endpoint:
        path = "/api/model" if args.scope == "bench" else "/api/outline"
        if args.scope == "unified":
            query = {}
            if args.detail != "steps":
                query["detail"] = args.detail
            if args.include_sensitive:
                query["include_sensitive"] = "true"
            if query:
                path += "?" + urlencode(query)
    return f"http://127.0.0.1:{port}{path}"


def _docs(scope: str) -> list[Path]:
    return [
        COLLECTION / "README.md",
        COLLECTION / ("cgabench" if scope == "bench" else "cgauv") / "README.md",
        COLLECTION / "cgawf" / "FLOW-SCRIPT-GUIDE.md",
    ]


def _bench_markdown(experiment: dict) -> str:
    from cgabench.model import MODES, STAGES

    mode = experiment.get("mode")
    fixed = MODES.get(mode)
    lines = [
        f"# CGA Bench: {experiment['name']}",
        "",
        f"- Mode: {mode or '(not selected)'}",
        f"- Fixed input: {fixed or '(select an experiment mode)'}",
        "- Reference: E.S[1] (S1)",
        f"- Active session: {experiment.get('active') or '(none)'}",
        f"- Comparison E.C: {experiment['C']['status']}",
        "- VIDs: :8x1 (experiment), :f3a (sessions), :b4z (comparison)",
        "",
        "Study one axis per experiment. Prepare D (databases) and Q (queries); "
        "J (jobs) and R (results) are derived by running.",
        "Variants inherit the accepted fixed input from S1. Comparison is explicit "
        "and always uses completed S1 as the baseline.",
    ]
    if not experiment["sessions"]:
        lines.extend(["", "No sessions. Create S1 with `cga bench session`."])
    for item in experiment["sessions"]:
        lines.extend([
            "",
            f"## E.S[{item['index']}]: {item['name']} ({item['vid']})",
            "",
            f"- User: {item['user']}",
            f"- Submission: {item['submission']}",
        ])
        for stage in STAGES:
            cell = item[stage]
            requirement = cell.get("requirement")
            suffix = f" - {requirement}" if requirement else ""
            lines.append(f"- E.S[{item['index']}].{stage}: {cell['status']}{suffix} "
                         f"({cell['vid']})")
    lines.extend([
        "",
        "Inspect full cells with `cga bench show E.S[N]` or `cga llm cb --json`.",
        "Dereference VIDs with `cga show :f3a,1,J`, `cga related :f3a,1,J`, "
        "or `cga open :f3a,1,J`. Short references use the current workflow/experiment/chain.",
        "Discover actions with `cga bench --help`; the running bench also describes "
        "its API at `/api/llm`.",
        "Query completed evidence through read-only `/api/results`; do not "
        "reingest or advance sessions merely to inspect results.",
    ])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    root = parser()
    args = root.parse_args(argv)
    if not hasattr(args, "scope"):
        (args.context_parser if args.command == "context" else root).print_help()
        return 0
    try:
        if args.show_docs:
            print("\n".join(str(path) for path in _docs(args.scope)))
            return 0
        if args.show_html_endpoint or args.show_json_endpoint:
            print(_endpoint(args))
            return 0
        if args.scope == "bench":
            from cgabench.model import projection
            from vid import Space

            if args.session_file:
                source = Path(args.session_file).expanduser().resolve()
                state = load_json(source)
                context = {"workflow": str(source), "chain": "raw",
                           "experiment": state.get("cgabench-experiment", {}).get("id", ""),
                           "frontier": ""}
            else:
                repository = Repository.discover()
                state = repository.current_state()
                context = Space(repository).context()
            document = projection(state)
            document["vid_context"] = context
            text = _bench_markdown(document)
            text += "\nVID context: " + json.dumps(context, sort_keys=True) + "\n"
        else:
            from cgauv.model import outline_markdown, outline_model

            document = outline_model(
                Repository.discover(), args.detail,
                include_sensitive=args.include_sensitive,
            )
            text = outline_markdown(document)
            text += (
                "\nInspect details with `cga step show ID`; search with "
                "`cga uv search QUERY`.\n"
                "Use `cga show VID`, `cga related VID`, or `cga open VID`; "
                "`cga show --registry` lists permanent roots.\n"
                "Use `cga llm cu --show-docs` for workflow and interface documentation.\n"
            )
        if args.json or os.environ.get("CGA_OUTPUT_JSON") == "1":
            print(json.dumps(document, indent=2, sort_keys=True))
        else:
            print(text, end="")
        return 0
    except (RepositoryError, WorkflowError, OSError, ValueError,
            argparse.ArgumentTypeError) as exc:
        root.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
