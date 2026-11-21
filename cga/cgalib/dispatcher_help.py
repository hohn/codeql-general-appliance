"""Help-only parsers for the Bash dispatcher and its shell/Go command groups."""

from __future__ import annotations

import argparse
from functools import lru_cache
from pathlib import Path
import subprocess
import sys

from command_help import enhance_parser, topics
from help_topics.workflow import (
    GETTING_STARTED_COMMANDS, GETTING_STARTED_READING, OVERVIEW, RUNNING_CGA,
)


COLLECTION = Path(__file__).resolve().parents[1]

def canonical_path(token: str) -> tuple[str, ...]:
    return {
        "h": ("help",), "a": ("assist",), "cn": ("chain",), "st": ("state",),
        "db-plan": ("db", "plan"), "db-build": ("db", "build"),
        "db-validate": ("db", "validate"), "vw": ("view",),
    }.get(token, (token,))


@lru_cache(maxsize=1)
def specification() -> list[list[str]]:
    result = subprocess.run(
        [COLLECTION / "cga", "__spec"],
        check=True, capture_output=True, text=True,
    )
    return [line.split() for line in result.stdout.splitlines() if line.strip()]


def build_parser(family: str = "") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"cga {family}".rstrip(), add_help=bool(family))
    if not family:
        parser.add_argument("-h", "--help", action="store_true", help="show this help message and exit")
        parser.add_argument(
            "-s", dest="getting_started", action="store_true",
            help="with -h, show the getting-started command walkthrough",
        )
        parser.add_argument("-C", metavar="DIR", help="operate from DIR")
        parser.add_argument("--cga-dir", metavar="DIR", help="use this .cga metadata directory")
        parser.add_argument("--store", metavar="ROOT", help="override the object-store root")
        parser.add_argument("--tag", action="append", help="tag recorded filter commands")
        parser.add_argument("--json", action="store_true", help="structured inspection output")
        parser.add_argument("--quiet", action="store_true", help="suppress workflow progress")
        parser.add_argument("--verbose", action="store_true", help="verbose workflow behavior")
        parser.add_argument("command", nargs="?", metavar="COMMAND", help="command from the list below")
        parser.add_argument("args", nargs=argparse.REMAINDER, help="command-specific arguments")
        rows = []
        registry = topics()
        for short, long, _tool, *_commands in specification():
            path = canonical_path(short)
            names = short if short == long else f"{short} | {long}"
            rows.append(f"{names:<30} {registry[path].summary}")
        parser.add_argument_group("Commands", "\n".join(rows))
    elif family == "help overview":
        add_overview_content(parser)
    elif family == "help getting-started":
        add_getting_started_content(parser)
    else:
        commands = next(row[3:] for row in specification() if row[0] == family)
        sub = parser.add_subparsers(dest="command")
        for command in commands:
            child = sub.add_parser(command)
            if family == "serve" and command in ("start", "status", "stop"):
                child.add_argument("--config", metavar="FILE", help="viewer workspace configuration JSON")
    return enhance_parser(parser, family)


def add_overview_content(parser: argparse.ArgumentParser) -> None:
    parser.add_argument_group("Overview", OVERVIEW)
    parser.add_argument_group("Running", RUNNING_CGA)


def add_getting_started_content(parser: argparse.ArgumentParser) -> None:
    parser.add_argument_group("Commands", GETTING_STARTED_COMMANDS)
    parser.add_argument_group("Further Reading", GETTING_STARTED_READING)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    family = args.pop(0) if args else ""
    parser = build_parser(family)
    if not args:
        parser.print_help()
        return 0
    if not family:
        selection = parser.parse_args(args)
        if selection.getting_started:
            if not selection.help or selection.command:
                parser.error("-s requires -h without a command; use cga -hs")
            parser = build_parser("help getting-started")
        parser.print_help()
        return 0
    parser.parse_args(["-h" if arg == "help" else arg for arg in args])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
