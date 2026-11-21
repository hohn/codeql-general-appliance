"""Keep local human-document links on rendered HTML, not Markdown sources."""

from __future__ import annotations

import argparse
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit, urlunsplit


ATTRIBUTE = re.compile(
    r"""(?P<name>[^\s"'<>/=]+)(?:\s*=\s*(?P<value>"[^"]*"|'[^']*'|[^\s"'=<>`]+))?"""
)


def llm_source(path: Path) -> bool:
    return path.name == "AGENTS.md" or ".agent-notes" in path.parts


def rendered_target(href: str, page: Path) -> str:
    target = urlsplit(href)
    if target.scheme or target.netloc or not target.path.endswith(".md"):
        return href
    destination = (page.parent / unquote(target.path)).resolve()
    if llm_source(destination):
        return href
    return urlunsplit(target._replace(path=target.path[:-3] + ".html"))


class MarkdownLinks(HTMLParser):
    def __init__(self, source: str, page: Path) -> None:
        super().__init__(convert_charrefs=False)
        self.page = page
        self.offsets = [0, *(match.end() for match in re.finditer("\n", source))]
        self.edits: list[tuple[int, int, str]] = []
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, attrs) -> None:
        if tag != "a":
            return
        raw = self.get_starttag_text()
        assert raw is not None
        line, column = self.getpos()
        offset = self.offsets[line - 1] + column
        for attribute in ATTRIBUTE.finditer(raw):
            if attribute["name"].lower() != "href" or attribute["value"] is None:
                continue
            start, end = attribute.span("value")
            if raw[start] in "\"'":
                start += 1
                end -= 1
            href = unescape(raw[start:end])
            target = rendered_target(href, self.page)
            if target != href:
                self.edits.append(
                    (offset + start, offset + end, escape(target, quote=True)),
                )

    handle_startendtag = handle_starttag


def rewrite_html(source: str, page: Path) -> str:
    if llm_source(page.resolve().with_suffix(".md")):
        return source
    parser = MarkdownLinks(source, page)
    for start, end, target in reversed(parser.edits):
        source = source[:start] + target + source[end:]
    return source


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="report changes without writing",
    )
    parser.add_argument("pages", nargs="+", type=Path)
    args = parser.parse_args()
    changed = False
    for page in args.pages:
        source = page.read_bytes().decode("utf-8")
        rendered = rewrite_html(source, page)
        if rendered == source:
            continue
        changed = True
        if args.check:
            print(f"{page}: human Markdown links must target HTML", file=sys.stderr)
        else:
            page.write_bytes(rendered.encode("utf-8"))
    return int(args.check and changed)


if __name__ == "__main__":
    raise SystemExit(main())
