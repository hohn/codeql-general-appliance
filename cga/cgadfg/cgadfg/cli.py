"""CLI for whole-CGAST data-flow and control-flow graph inspection."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from command_help import enhance_parser

from .graph import (
    Graph,
    GraphError,
    control_dot_graph,
    control_markdown_table,
    control_plain_table,
    control_user_html,
    data_dot_graph,
    data_markdown_table,
    data_plain_table,
    data_user_html,
)


COMPONENT = "cgadfg"


def _cga_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_manifest() -> Path:
    history_dir = os.environ.get("CGA_HISTORY_DIR")
    if history_dir:
        return Path(history_dir).expanduser() / "manifest.json"
    tmp_dir = Path(os.environ.get("CGA_TMPDIR", _cga_root() / "cga-tmp"))
    return tmp_dir.expanduser() / "mrva-flow-history" / "manifest.json"


def _session_path(graph: Graph, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    history = graph.manifest_path.parent
    name = history.name.removesuffix("-history") + ".json"
    return history.parent / name


def _display_path(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _info_lines(graph: Graph, session: Path) -> list[str]:
    history = graph.manifest_path.parent
    snapshots = history / "nodes"
    lines = [
        f"Graph manifest: {graph.manifest_path.name}",
        f"Immutable state snapshots: {_display_path(snapshots, history)}",
        f"Current-head compatibility copy: {_display_path(session, history.parent)}",
        "",
        "For this run, the manifest records:",
    ]
    for chain_id in graph.chain_ids:
        nodes = graph.chain_nodes(chain_id)
        root = graph.root(chain_id)
        head = graph.chain_head(chain_id)
        lines.extend([
            f"Chain: cga_{chain_id}",
            f"Root: {root.id if root else '(none)'}",
            f"Head: {head.id if head else '(none)'}",
            f"Immutable states: {len(nodes)}",
        ])
        if chain_id != graph.chain_ids[-1]:
            lines.append("")
    lines.extend([
        "",
        "Each manifest node contains:",
        "id and parent, defining graph topology",
        "chain_id and sequence",
        "numbered source_step",
        "complete component command",
        "timestamp",
        "path to the full CGAST snapshot",
    ])
    return lines


def render_info(
        graph: Graph, session: Path, markdown: bool,
        control_flow: bool = False) -> str:
    lines = _info_lines(graph, session)
    graph_name = "Control-Flow" if control_flow else "Data-Flow"
    if not markdown:
        return f"Graph type: Whole-CGAST {graph_name}\n" + "\n".join(lines) + "\n"
    output = [
        f"# Whole-CGAST {graph_name} Graph",
        "",
        f"- **Graph manifest:** `{lines[0].split(': ', 1)[1]}`",
        f"- **Immutable state snapshots:** `{lines[1].split(': ', 1)[1]}`",
        f"- **Current-head compatibility copy:** `{lines[2].split(': ', 1)[1]}`",
        "",
        "## Run",
        "",
    ]
    for chain_id in graph.chain_ids:
        root = graph.root(chain_id)
        head = graph.chain_head(chain_id)
        output.extend([
            f"### `cga_{chain_id}`",
            "",
            f"- **Root:** `{root.id if root else '(none)'}`",
            f"- **Head:** `{head.id if head else '(none)'}`",
            f"- **Immutable states:** {len(graph.chain_nodes(chain_id))}",
            "",
        ])
    output.extend([
        "## Node Metadata",
        "",
        "Each manifest node contains:",
        "",
        "- `id` and `parent`, defining graph topology",
        "- `chain_id` and `sequence`",
        "- numbered `source_step`",
        "- complete component `command`",
        "- timestamp",
        "- path to the full CGAST snapshot",
    ])
    return "\n".join(output) + "\n"


def build_parser(control_flow: bool = False) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=COMPONENT,
        description="Inspect immutable whole-CGAST run graphs.",
    )
    parser.add_argument(
        "--manifest", type=Path, default=None,
        help="history manifest (default: CGA_HISTORY_DIR or mrva-flow)")
    parser.add_argument(
        "--session", default=None,
        help="current-head compatibility copy shown by info")
    parser.add_argument(
        "--control-flow", action="store_true", help=argparse.SUPPRESS)
    formats = parser.add_mutually_exclusive_group()
    formats.add_argument(
        "-m", "--markdown", action="store_true",
        help="format info or show output as Markdown")
    formats.add_argument(
        "-d", "--dot", action="store_true",
        help="format show output as Graphviz DOT")
    formats.add_argument(
        "-r", "--render", metavar="FILE.pdf",
        help="render show output to a PDF with Graphviz dot")
    formats.add_argument(
        "-u", "--render-user", metavar="FILE.html",
        help="render a simplified interactive HTML graph")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("info", help="summarize graph storage and chains")
    subparsers.add_parser("show", help="show graph nodes and edges")
    return enhance_parser(parser, "cfg" if control_flow else "dfg")


def main(argv: list[str]) -> int:
    parser = build_parser(control_flow="--control-flow" in argv)
    args = parser.parse_args(argv)
    if args.command == "info" and (
            args.dot or args.render or args.render_user):
        parser.error("--dot, --render, and --render-user apply only to show")
    manifest = (args.manifest or _default_manifest()).expanduser().resolve()
    try:
        graph = Graph.load(manifest)
        if args.control_flow:
            dot_renderer = control_dot_graph
            markdown_renderer = control_markdown_table
            plain_renderer = control_plain_table
            user_renderer = control_user_html
        else:
            dot_renderer = data_dot_graph
            markdown_renderer = data_markdown_table
            plain_renderer = data_plain_table
            user_renderer = data_user_html
        if args.command == "info":
            sys.stdout.write(render_info(
                graph, _session_path(graph, args.session), args.markdown,
                args.control_flow))
        elif args.render_user:
            destination = Path(args.render_user).expanduser().resolve()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(user_renderer(graph), encoding="utf-8")
            print(destination)
        elif args.render:
            destination = Path(args.render).expanduser().resolve()
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".dot", encoding="utf-8") as stream:
                stream.write(dot_renderer(graph))
                stream.flush()
                subprocess.run(
                    ["dot", "-Tpdf", stream.name, "-o", str(destination)],
                    check=True)
            print(destination)
        elif args.dot:
            sys.stdout.write(dot_renderer(graph))
        elif args.markdown:
            sys.stdout.write(markdown_renderer(graph))
        else:
            sys.stdout.write(plain_renderer(graph))
    except GraphError as error:
        parser.error(str(error))
    except FileNotFoundError as error:
        parser.error(f"required executable not found: {error.filename}")
    except subprocess.CalledProcessError as error:
        parser.error(f"Graphviz dot failed with exit status {error.returncode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))