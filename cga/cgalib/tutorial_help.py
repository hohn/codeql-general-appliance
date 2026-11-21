"""Read-only help chapters sourced from the canonical Start here guides."""

from dataclasses import dataclass
from pathlib import Path
import re

from command_help import HelpTopic


ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Tutorial:
    name: str
    label: str
    source: str
    summary: str
    chapters: tuple[tuple[str, str], ...]


TUTORIALS = (
    Tutorial(
        "bash-tutorial-sql", "bash example -- sqlite tutorial",
        "cga/cgaassist/README.md",
        "Read the SQLite Bash tutorial in chapter-sized help pages.",
        (
            ("setup", "Set up the toy workspace"),
            ("build-collection", "Build a database collection"),
            ("llm-supervision", "LLM-supervised attempts"),
            ("query-authoring", "Set up query authoring"),
            ("injection-query", "Author the injection query"),
            ("save-publish", "Save drafts and publish"),
            ("paired-experiment", "SQLite injection: publish, patch, rebuild, and compare"),
            ("patch", "Patch the toy and prepare the shared dependency"),
            ("build-pair", "Build both revisions in both modes"),
            ("publish-collection", "Publish the four-database collection"),
            ("mrva", "Run the published query on all four through MRVA"),
            ("ingest", "Combine the results in DuckDB"),
            ("compare", "Compare in DuckDB and return later"),
            ("check", "Fixed SQLite toy check"),
        ),
    ),
    Tutorial(
        "mrva-flow", "single-user MRVA flow", "cga/mrva-flow/README.md",
        "Read the single-user MRVA flow: selection, execution, ingestion, and export.",
        (("run", "Run it"), ("inspect", "Inspect the flow"), ("flow", "Flow")),
    ),
    Tutorial(
        "bench-intro", "Bench introductory outline", "guides/introductory/bench.md",
        "Read the Bench introduction: experiments, sessions, comparison, and viewers.",
        (
            ("start", "Start an experiment"),
            ("sessions", "Work with inputs and sessions"),
            ("compare", "Inspect and compare"),
            ("viewers", "Reconnect, stop, and restart"),
            ("next", "Next"),
        ),
    ),
    Tutorial(
        "shell-workflow", "shell workflow introductory outline",
        "guides/introductory/cli-workflow.md",
        "Read the shell workflow: preparation, analysis, results, and viewers.",
        (
            ("setup", "Before starting"),
            ("prepare", "CGA preparation: prepare inputs"),
            ("apply", "Apply queries"),
            ("results", "Result inspection"),
            ("viewers", "Viewers: reconnect and stop"),
        ),
    ),
    Tutorial(
        "two-user-standalone", "two-user standalone walkthrough (sample-05-i)",
        "cga/sample-05-i/README.md",
        "Read the earlier standalone two-user MRVA walkthrough.",
        (
            ("background", 'What "standalone" changes vs. sample-05'),
            ("run", "Run it"),
            ("state", "Components and state"),
        ),
    ),
    Tutorial(
        "two-user-workflow", "two-user walkthrough (sample-05)",
        "cga/sample-05/README.md",
        "Read the earlier operator-driven two-user MRVA walkthrough.",
        (("run", "Run it"), ("state", "Components and state")),
    ),
    Tutorial(
        "zlib-study", "zlib preparation and MRVA study (query-030)",
        "cga/analysis/CVE-2016-9843/query-030/README.md",
        "Read the architecture-specific zlib preparation and MRVA study.",
        (
            ("prepare", "Componentized preparation"),
            ("mrva", "Explicit MRVA lifecycle"),
            ("results", "Expected result"),
        ),
    ),
)
BY_NAME = {tutorial.name: tutorial for tutorial in TUTORIALS}
READ_ONLY = (
    "Displaying this tutorial never executes its commands or changes workflow\n"
    "state. Copy commands into Bash yourself, in chapter order. Restore required\n"
    "variables in a fresh shell, and reuse retained artifacts instead of\n"
    "repeating their creation."
)


def link_text(match: re.Match[str], tutorial: Tutorial) -> str:
    label, target = match.groups()
    for name, title in tutorial.chapters:
        anchor = re.sub(r"[^\w -]", "", title.lower()).replace(" ", "-")
        if target == "#" + anchor:
            target = f"cga help {tutorial.name} {name}"
            break
    return f"{label} ({target})"


def plain_text(markdown: str, tutorial: Tutorial) -> str:
    lines = []
    in_code = False
    for line in markdown.strip().splitlines():
        if line.startswith("```"):
            in_code = not in_code
            continue
        if not in_code:
            line = re.sub(r"\[([^]]+)\]\(([^)]+)\)",
                          lambda match: link_text(match, tutorial), line)
            line = re.sub(r"`([^`]+)`", r"\1", line).replace("**", "")
            if line.startswith("# "):
                line = line[2:]
        lines.append(line)
    if in_code:
        raise ValueError(f"unclosed code fence in tutorial: {tutorial.source}")
    return "\n".join(lines)


def content(tutorial: Tutorial, source: Path | None = None) -> tuple[str, dict[str, str]]:
    source = source or ROOT / tutorial.source
    blocks: list[list[str]] = [[]]
    headings = []
    in_code = False
    for line in source.read_text(encoding="utf-8").splitlines(keepends=True):
        if line.startswith("```"):
            in_code = not in_code
        heading = None if in_code else re.fullmatch(r"#{2,3} (.+)", line.rstrip("\r\n"))
        if heading:
            headings.append(heading[1])
            blocks.append([])
        else:
            blocks[-1].append(line)
    expected = [title for _name, title in tutorial.chapters]
    if headings != expected:
        raise ValueError(f"tutorial headings changed; update chapters for {source}")
    return plain_text("".join(blocks[0]), tutorial), {
        name: plain_text("".join(body), tutorial)
        for (name, _title), body in zip(tutorial.chapters, blocks[1:])
    }


def help_topics() -> dict[tuple[str, ...], HelpTopic]:
    result = {}
    for tutorial in TUTORIALS:
        path = ("help", tutorial.name)
        result[path] = HelpTopic(
            tutorial.summary, READ_ONLY,
            (f"cga help {tutorial.name}",
             f"cga help {tutorial.name} {tutorial.chapters[0][0]}"),
        )
        for name, title in tutorial.chapters:
            result[(*path, name)] = HelpTopic(
                title + ".", READ_ONLY,
                (f"cga help {tutorial.name} {name}", f"cga help {tutorial.name}"),
            )
    return result


def add_parser(subparsers) -> None:
    for tutorial in TUTORIALS:
        overview, chapters = content(tutorial)
        parser = subparsers.add_parser(tutorial.name)
        parser.set_defaults(tutorial_page=parser)
        parser.add_argument_group("Overview", overview)
        parser.add_argument_group(
            "Further Reading",
            f"Original linear write-up: {Path(tutorial.source).with_suffix('.html')}\n"
            f"Canonical source and relative document links: {tutorial.source}",
        )
        steps = parser.add_subparsers(dest="tutorial_chapter", metavar="CHAPTER")
        for name, _title in tutorial.chapters:
            chapter = steps.add_parser(name)
            chapter.set_defaults(tutorial_page=chapter)
            chapter.add_argument_group("Walkthrough", chapters[name])
