"""Shared, native argparse help for the public CGA command tree."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from functools import lru_cache, partial
import textwrap


@dataclass(frozen=True)
class HelpTopic:
    summary: str
    description: str
    examples: tuple[str, ...]
    environment: tuple[tuple[str, str], ...] = ()


@lru_cache(maxsize=1)
def topics() -> dict[tuple[str, ...], HelpTopic]:
    from help_topics import analysis, preparation, views, workflow

    result: dict[tuple[str, ...], HelpTopic] = {}
    for module in (analysis, preparation, views, workflow):
        for path, topic in module.TOPICS.items():
            if path in result:
                raise ValueError(f"duplicate CGA help topic: {' '.join(path)}")
            result[path] = topic
    return result


class CommandHelpFormatter(argparse.RawDescriptionHelpFormatter):
    def __init__(
        self, *args, topic: HelpTopic, notes: str | None = None, **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.topic = topic
        self.notes = notes

    def add_usage(self, usage, actions, groups, prefix=None) -> None:
        self.start_section("Name")
        self.add_text(self._prose(f"{self._prog} - {self.topic.summary}"))
        self.end_section()
        super().add_usage(
            usage, actions, groups,
            prefix="Synopsis: " if prefix is None else prefix,
        )

    def start_section(self, heading: str | None) -> None:
        super().start_section(heading.title() if heading else heading)

    def _prose(self, text: str, indent: str = "") -> str:
        return "\n\n".join(
            textwrap.fill(
                paragraph, width=max(20, self._width - self._current_indent),
                initial_indent=indent, subsequent_indent=indent,
            )
            for paragraph in text.split("\n\n")
        )

    def format_help(self) -> str:
        self.start_section("Description")
        self.add_text(self._prose(self.topic.description))
        self.end_section()
        if self.topic.environment:
            self.start_section("Environment Variables")
            for name, description in self.topic.environment:
                self.add_text(f"{name}\n{self._prose(description, '  ')}")
            self.end_section()
        if self.notes:
            self.start_section("Notes")
            self.add_text(self.notes)
            self.end_section()
        self.start_section("Example")
        self.add_text("\n".join(self.topic.examples))
        self.end_section()
        return super().format_help()


def enhance_parser(
    parser: argparse.ArgumentParser,
    family: str,
) -> argparse.ArgumentParser:
    """Document a parser and its visible subcommands without changing execution."""
    registry = topics()

    def visit(current: argparse.ArgumentParser, path: tuple[str, ...]) -> None:
        topic = registry.get(path)
        if topic is None:
            raise ValueError(f"missing CGA help topic: cga {' '.join(path)}")
        current.prog = " ".join(("cga", *path))
        notes = "\n\n".join(
            text for text in (current.description, current.epilog)
            if text and text not in (topic.description, topic.summary)
        )
        current.description = None
        current.epilog = None
        current.formatter_class = partial(
            CommandHelpFormatter, topic=topic, notes=notes or None,
        )
        for action in current._actions:
            if not isinstance(action, argparse._SubParsersAction):
                continue
            hidden = {
                choice.dest for choice in action._choices_actions
                if choice.help == argparse.SUPPRESS
            }
            seen: set[int] = set()
            for name, child in action.choices.items():
                if name in hidden or id(child) in seen:
                    continue
                seen.add(id(child))
                visit(child, (*path, name))
                choices = [
                    choice for choice in action._choices_actions
                    if choice.dest == name
                ]
                summary = registry[(*path, name)].summary
                if choices:
                    choices[0].help = summary
                else:
                    aliases = [
                        alias for alias, candidate in action.choices.items()
                        if candidate is child and alias != name
                    ]
                    action._choices_actions.append(
                        action._ChoicesPseudoAction(name, aliases, summary)
                    )

    visit(parser, tuple(family.split()))
    return parser
