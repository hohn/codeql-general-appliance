"""Export an offline, read-only browser for the authoritative CGA CLI help."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import TypedDict
from urllib.parse import quote

from command_help import enhance_parser, topics
from dispatcher_help import (
    add_getting_started_content,
    add_overview_content,
    build_parser as build_dispatcher_parser,
    canonical_path,
    specification,
)
import sample_help
import tutorial_help
from vid_registry import REGISTRY, reference


COLLECTION = Path(__file__).resolve().parents[1]
ASSETS = Path(__file__).with_name("help_static")
VID_ASSETS = Path(__file__).with_name("vid_static")
INTERNAL_PATHS = {("uv", "serve")}
HEADING = re.compile(r"^([A-Z][A-Za-z0-9 /()-]*): ?(.*)$")
TASK_GROUPS = (
    ("Create databases", (
        "assist", "catalog", "codeql", "control", "cve", "database", "db-build",
        "db-plan", "db-validate", "postgres", "src-prep",
    )),
    ("Write and prepare queries", (
        "assist", "bench", "codeql", "coder", "cve", "query-gen", "query-lib",
    )),
    ("Apply queries", (
        "bench", "db-lib", "db-serve", "local-mrva", "mrva-request",
        "mrva-server", "query-lib", "run", "serve", "user-view",
    )),
    ("Review results", (
        "bench", "control-flow-graph", "data-flow-graph", "export", "header",
        "llm", "open", "related", "sarif-ingest", "show", "unified-view", "view",
    )),
)


class Link(TypedDict):
    id: str
    label: str
    match: str
    command: str
    summary: str


class DocumentLink(TypedDict):
    label: str
    href: str
    summary: str


class Section(TypedDict):
    heading: str
    text: str


class Page(TypedDict):
    command: str
    sections: list[Section]
    children: list[Link]


class TaskGroup(TypedDict):
    label: str
    commands: list[Link]


class HelpModel(TypedDict):
    generated_at: str
    start_here: list[Link | DocumentLink]
    tutorial_documents: list[DocumentLink]
    system_tests: list[DocumentLink]
    llm_start_here: list[Link | DocumentLink]
    tree: list[Link]
    task_groups: list[TaskGroup]
    pages: dict[str, Page]


def command_name(path: tuple[str, ...]) -> str:
    return " ".join(("cga", *path))


def command_links(path: tuple[str, ...]) -> list[Link]:
    registry = topics()
    if not path:
        return [
            Link(
                id=command_name(canonical_path(short)),
                label=long,
                match=short if short == long else f"{short} | {long}",
                command=f"{command_name(canonical_path(short))} -h",
                summary=registry[canonical_path(short)].summary,
            )
            for short, long, _tool, *_commands in specification()
        ]
    return [
        Link(
            id=command_name(child), label=child[-1], match=child[-1],
            command=f"{command_name(child)} -h", summary=topic.summary,
        )
        for child, topic in registry.items()
        if child not in INTERNAL_PATHS
        and len(child) == len(path) + 1 and child[:-1] == path
    ]


def split_sections(text: str) -> list[Section]:
    sections: list[Section] = []
    for line in text.splitlines():
        match = HEADING.match(line)
        if match:
            sections.append(Section(heading=match[1], text=match[2]))
        elif sections:
            sections[-1]["text"] += "\n" + line
        elif line.strip():
            raise ValueError(f"unrecognized help preamble: {line}")
    if not sections or sections[0]["heading"] != "Name":
        raise ValueError("help output has no Name section")
    for section in sections:
        section["text"] = section["text"].strip("\n")
    return sections


def capture_help(path: tuple[str, ...]) -> list[Section]:
    result = subprocess.run(
        [COLLECTION / "cga", *path, "-h"],
        input="", capture_output=True, text=True, timeout=30,
        env={**os.environ, "PYTHON_COLORS": "0", "NO_COLOR": "1"},
    )
    if result.returncode:
        raise ValueError(
            f"{command_name(path)} -h failed ({result.returncode}):\n"
            f"{result.stdout}{result.stderr}"
        )
    return split_sections(result.stdout + result.stderr)


def collect_help() -> HelpModel:
    root = Link(
        id="cga", label="cga index", match="cga", command="cga -h",
        summary=topics()[()].summary,
    )
    tree = [root]
    seen = {"cga"}
    for link in command_links(()):
        if link["id"] not in seen:
            tree.append(link)
            seen.add(link["id"])
        else:
            existing = next(item for item in tree if item["id"] == link["id"])
            existing["match"] += f" | {link['match']}"
    tree[1:] = sorted(tree[1:], key=lambda link: link["label"].casefold())
    by_label = {link["label"]: link for link in tree}
    task_groups = [
        TaskGroup(label=label, commands=[by_label[name] for name in names])
        for label, names in TASK_GROUPS
    ]
    paths = {(): root}
    for node in tree[1:]:
        path = tuple(node["id"].split()[1:])
        paths[path] = node
        for child in command_links(path):
            paths[tuple(child["id"].split()[1:])] = child
    for path in (("help", "sample"), ("help", "sample", "05"), ("llm", "context"),
                 *(("help", tutorial.name) for tutorial in tutorial_help.TUTORIALS)):
        for child in command_links(path):
            paths[tuple(child["id"].split()[1:])] = child
    if os.environ.get("CGA_QUIET") != "1":
        print(f"Collecting {len(paths)} CGA help pages...", file=sys.stderr)
    pages = {
        command_name(path): Page(
            command=command_name(path),
            sections=capture_help(path),
            children=command_links(path),
        )
        for path in paths
    }
    return HelpModel(
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        start_here=[
            DocumentLink(
                label="Visual overview", href="docs/cga-overview.html",
                summary="Understand CGA, follow the fixed Sample 05 example, and install.",
            ),
            DocumentLink(
                label="Reference manual", href="docs/book/index.html",
                summary="Detailed workflows, components, and operations; consult as needed.",
            ),
            Link(
                id="cga help overview", label="CGA overview",
                match="overview", command="cga help overview",
                summary=topics()[("help", "overview")].summary,
            ),
            Link(
                id="cga help getting-started", label="getting started",
                match="getting-started", command="cga help getting-started",
                summary=topics()[("help", "getting-started")].summary,
            ),
            Link(
                id="cga help bash-tutorial-sql", label="bash example -- sqlite tutorial",
                match="bash-tutorial-sql", command="cga help bash-tutorial-sql",
                summary=topics()[("help", "bash-tutorial-sql")].summary,
            ),
            Link(
                id="cga help sample 05", label="sample 05",
                match="sample 05", command="cga help sample 05",
                summary=topics()[("help", "sample", "05")].summary,
            ),
            *[Link(
                id=f"cga help {tutorial.name}", label=tutorial.label,
                match=tutorial.name, command=f"cga help {tutorial.name}",
                summary=tutorial.summary,
            ) for tutorial in tutorial_help.TUTORIALS[1:]],
        ],
        tutorial_documents=[
            *[DocumentLink(
                label=tutorial.label,
                href=str(Path(tutorial.source).with_suffix(".html")),
                summary="Original linear write-up. " + tutorial.summary,
            ) for tutorial in tutorial_help.TUTORIALS],
            DocumentLink(
                label="Reference manual",
                href="docs/book/index.html",
                summary="Detailed reference. Build with make -C docs book.",
            ),
        ],
        system_tests=[
            DocumentLink(
                label="System tests / sample workflows",
                href="cga/system-tests/README.html",
                summary="Phase-based MRVA scenarios, configuration, and end-to-end verification.",
            ),
        ],
        llm_start_here=[
            DocumentLink(
                label="LLM exploration guide", href="docs/cga-help-llm.org",
                summary="Choose one task route, inspect current evidence, and stop reading when the task is answerable.",
            ),
            DocumentLink(
                label="agent core", href=".agent-notes/README.md",
                summary="Short repository invariants and focused contributor topic routes.",
            ),
            Link(
                id="cga llm context", label="live workflow and experiment context",
                match="context", command="cga llm context -h",
                summary=topics()[("llm", "context")].summary,
            ),
            DocumentLink(
                label="LLM-guided two-user walkthrough", href="cga/llm-walkthrough-instructions.org",
                summary="Earlier prototype: guide a human through one visible shell operation at a time.",
            ),
            DocumentLink(
                label="flow-script authoring guide", href="cga/cgawf/FLOW-SCRIPT-GUIDE.md",
                summary="Inputs, operation boundaries, tags, and review rules for LLM-authored CGA scripts.",
            ),
            DocumentLink(
                label="advanced reading map", href="READING-GUIDE.md",
                summary="Fallback structural and task map when focused investigation cannot identify the owner.",
            ),
        ],
        tree=tree, task_groups=task_groups, pages=pages,
    )


def render_document(model: HelpModel, destination: Path | None = None) -> str:
    destination = destination or COLLECTION.parent / "docs/cga-help.html"
    resolved = dict(model)
    for group in ("start_here", "llm_start_here", "tutorial_documents", "system_tests"):
        resolved[group] = [
            {**link, "href": quote(Path(os.path.relpath(
                COLLECTION.parent / link["href"], destination.parent,
            )).as_posix())}
            if "href" in link else link
            for link in model[group]
        ]
    elements = [entry for entry in REGISTRY if entry["selectors"].get("help")]
    targets = {
        entry["vid"]: entry for entry in elements if entry["kind"] == "control"
    }
    for command, page in model["pages"].items():
        path = command.split()[1:]
        target = {"label": command, "kind": "help-page", "command": command}
        targets[reference("help-pages", *path)] = target
        for section in page["sections"]:
            slug = re.sub(r"[^a-z0-9]+", "-", section["heading"].lower()).strip("-")
            ref = reference("help-pages", *path, "section", slug)
            if ref in targets:
                raise ValueError(f"duplicate help section reference: {ref}")
            targets[ref] = {**target, "label": section["heading"],
                            "kind": "help-section", "section": section["heading"]}
    documents = {}
    for group in ("start_here", "llm_start_here", "tutorial_documents", "system_tests"):
        for original, link in zip(model[group], resolved[group]):
            if "href" not in original:
                continue
            ref = reference("help-documents", "p" + hashlib.sha256(
                original["href"].encode("utf-8"),
            ).hexdigest())
            documents[link["href"]] = ref
            targets[ref] = {
                "kind": "help-document", "label": link["label"],
                "href": link["href"], "source": original["href"],
            }
    groups = {}
    for group in model["task_groups"]:
        ref = reference("help-groups", re.sub(
            r"[^a-z0-9]+", "-", group["label"].lower(),
        ).strip("-"))
        groups[group["label"]] = ref
        targets[ref] = {"kind": "help-group", "label": group["label"],
                        "commands": [command["id"] for command in group["commands"]]}
    resolved["references"] = {
        "elements": elements, "targets": targets, "documents": documents, "groups": groups,
    }
    snapshot = {key: value for key, value in resolved.items() if key != "generated_at"}
    resolved["references"]["generation"] = "g" + hashlib.sha256(json.dumps(
        snapshot, sort_keys=True, ensure_ascii=True,
    ).encode("utf-8")).hexdigest()
    document = (ASSETS / "index.html").read_text(encoding="utf-8")
    document = document.replace(
        "{{STYLE}}", (ASSETS / "help.css").read_text(encoding="utf-8"),
    ).replace(
        "{{SCRIPT}}", (ASSETS / "help.js").read_text(encoding="utf-8"),
    ).replace(
        "{{VID_STYLE}}", (VID_ASSETS / "vid.css").read_text(encoding="utf-8"),
    ).replace(
        "{{VID_SCRIPT}}", (VID_ASSETS / "badges.js").read_text(encoding="utf-8"),
    ).replace(
        "{{REFERENCE_SCRIPT}}", (ASSETS / "references.js").read_text(encoding="utf-8"),
    )
    data = json.dumps(resolved, ensure_ascii=True).replace("<", "\\u003c")
    return document.replace("{{DATA}}", data)


def export(destination: Path) -> None:
    destination = destination.expanduser().absolute()
    document = render_document(collect_help(), destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent,
            prefix=f".{destination.name}.", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(document)
        temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(destination)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cga help")
    parser.add_argument(
        "--export", metavar="HTML", type=Path,
        help="write a self-contained help browser to HTML (replaces the destination)",
    )
    sub = parser.add_subparsers(dest="topic")
    overview = sub.add_parser("overview")
    add_overview_content(overview)
    guide = sub.add_parser("getting-started")
    add_getting_started_content(guide)
    tutorial_help.add_parser(sub)
    sample_help.add_parser(sub)
    enhance_parser(parser, "help")
    sample_help.format_recipes(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        parser = build_parser()
    except (OSError, ValueError) as error:
        print(f"cga help: {error}", file=sys.stderr)
        return 1
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "sample-05":
        arguments[:1] = ["sample", "05"]
    args = parser.parse_args(arguments)
    if args.topic in tutorial_help.BY_NAME:
        if args.export is not None:
            parser.error(f"{args.topic} cannot be combined with --export")
        args.tutorial_page.print_help()
        return 0
    if args.topic in ("sample", "s"):
        if args.export is not None:
            parser.error("sample cannot be combined with --export")
        step = getattr(args, "sample_recipe", None)
        if step is not None and args.action in ("run", "r"):
            return sample_help.run(step)
        path = ("help", "sample")
        if args.sample is not None:
            path += (args.sample,)
        if step is not None:
            path += (step.number,)
        current = parser
        for token in path[1:]:
            action = next(
                action for action in current._actions
                if isinstance(action, argparse._SubParsersAction)
            )
            current = action.choices[token]
        current.print_help()
        return 0
    if args.topic in ("overview", "getting-started"):
        if args.export is not None:
            parser.error(f"{args.topic} cannot be combined with --export")
        build_dispatcher_parser(f"help {args.topic}").print_help()
        return 0
    if args.export is None:
        parser.error("choose overview, a tutorial, sample, getting-started, or --export HTML")
    try:
        export(args.export)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f"cga help: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
