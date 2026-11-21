"""Build a documentation-only GitHub Pages artifact using standard-library Python."""

from __future__ import annotations

import argparse
from collections import deque
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
import posixpath
import re
import subprocess
import sys
import tempfile
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from html_links import ATTRIBUTE


ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = {".html", ".htm", ".md", ".org", ".pdf"}
ASSETS = {
    ".css", ".js", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
    ".woff", ".woff2", ".ttf", ".otf",
}
ENTRIES = {
    "index.html", "README.html", "docs/index.html", "docs/cga-overview.html",
    "docs/cga-help.html", "docs/cga-sample-05.html",
}
CSS_URL = re.compile(
    r"""url\(\s*(['"]?)(.*?)\1\s*\)|@import\s+['"]([^'"]+)['"]""",
    re.IGNORECASE,
)


def github_repository(root: Path) -> str:
    remote = subprocess.check_output(
        ["git", "-C", str(root), "remote", "get-url", "origin"],
        text=True, stderr=subprocess.PIPE,
    ).strip()
    match = re.fullmatch(
        r"(?:git@github\.com:|https://github\.com/|ssh://git@github\.com/)"
        r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?",
        remote,
    )
    if not match:
        raise ValueError("origin must identify a GitHub repository using HTTPS or SSH")
    return match[1]


def permitted(name: str) -> bool:
    parts = PurePosixPath(name).parts
    return (
        bool(parts) and not name.startswith("/")
        and not any(part in {"..", "node_modules", "__pycache__", "scratch", "tmp",
                             "runtime", "vendor"} for part in parts)
        and not any(part.startswith(".") and part != ".agent-notes" for part in parts)
        and not any(part.startswith(("cga-tmp", "cga-prep-tmp")) for part in parts)
        and not name.startswith(("docs/src/", "notes/src/"))
    )


def redirect(target: str) -> str:
    safe = escape(target, quote=True)
    return (
        '<!doctype html>\n<html lang="en"><meta charset="utf-8">\n'
        f'<meta http-equiv="refresh" content="0;url={safe}">\n'
        '<title>CGA documentation</title>\n'
        f'<a href="{safe}">Open documentation</a>\n'
        '<script>location.replace('
        f'document.querySelector("a").getAttribute("href")'
        '+location.search+location.hash);</script>\n</html>\n'
    )


class PublishedHTML(HTMLParser):
    def __init__(self, source: str, rewrite) -> None:
        super().__init__(convert_charrefs=False)
        self.rewrite = rewrite
        self.offsets = [0, *(match.end() for match in re.finditer("\n", source))]
        self.edits = []
        self.ids = set()
        self.links = []
        self.redirect = None
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, attrs) -> None:
        values = dict(attrs)
        if "id" in values:
            self.ids.add(values["id"])
        if tag == "a" and values.get("name"):
            self.ids.add(values["name"])
        if tag == "meta" and values.get("http-equiv", "").lower() == "refresh":
            refresh = re.fullmatch(r"\s*[\d.]+\s*;\s*url=(.*)", values.get("content", ""), re.I)
            if refresh:
                self.redirect = refresh[1]
        raw = self.get_starttag_text()
        assert raw is not None
        line, column = self.getpos()
        offset = self.offsets[line - 1] + column
        for attribute in ATTRIBUTE.finditer(raw):
            name = attribute["name"].lower()
            if name not in {"href", "src", "poster", "data"} or attribute["value"] is None:
                continue
            start, end = attribute.span("value")
            if raw[start] in "\"'":
                start += 1
                end -= 1
            original = unescape(raw[start:end])
            target = self.rewrite(original, tag == "a" and name == "href")
            self.links.append((target, tag == "a" and name == "href"))
            if target != original:
                self.edits.append((offset + start, offset + end, escape(target, quote=True)))

    handle_startendtag = handle_starttag

    def render(self, source: str) -> str:
        for start, end, target in reversed(self.edits):
            source = source[:start] + target + source[end:]
        return source


def local_target(page: str, href: str) -> str | None:
    link = urlsplit(href)
    if link.scheme or link.netloc:
        return None
    if not link.path:
        return page
    if link.path.startswith("/"):
        raise ValueError(f"{page}: root-absolute URL breaks project Pages: {href}")
    name = posixpath.normpath(posixpath.join(posixpath.dirname(page), unquote(link.path)))
    if name == ".." or name.startswith("../"):
        raise ValueError(f"{page}: URL escapes documentation root: {href}")
    return name


def publish(root: Path, output: Path) -> tuple[int, str]:
    root = root.resolve()
    output = output.absolute()
    if output.is_symlink() or any(parent.is_symlink() for parent in output.parents):
        raise ValueError("publication output and its parents must not be symlinks")
    output = output.resolve()
    if root == output or root.is_relative_to(output):
        raise ValueError("publication output must not contain the source checkout")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError(f"publication output must be absent or empty: {output}")
    repository = github_repository(root)
    revision = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True,
    ).strip()
    tracked = set(filter(None, subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "-z"], text=True,
    ).split("\0")))

    def tracked_source(name: str) -> Path:
        source = (root / name).resolve()
        if not source.is_relative_to(root) or source.relative_to(root).as_posix() not in tracked:
            raise ValueError(f"documentation has an external or untracked symlink target: {name}")
        return source

    directories = {str(parent) for name in tracked for parent in PurePosixPath(name).parents}
    pending = deque(sorted(
        name for name in tracked if permitted(name) and (
            Path(name).suffix in {".md", ".org"} or name in ENTRIES
            or (Path(name).suffix == ".html"
                and any(str(Path(name).with_suffix(suffix)) in tracked
                        for suffix in (".md", ".org")))
            or name == "LICENSE"
        ) and not (root / name).is_symlink()
    ))
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cga-pages-book-") as directory:
        book = Path(directory)
        for name in sorted(tracked):
            if name != "docs/book.toml" and not name.startswith("docs/src/"):
                continue
            source = tracked_source(name)
            target = book / name[len("docs/"):]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        subprocess.run(
            ["mdbook", "build", str(book), "--dest-dir", str(output / "docs/book")],
            check=True,
        )
    built = {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()}
    if any(path.is_symlink() for path in output.rglob("*")):
        raise ValueError("reference book output contains a symlink")
    pending.extend(sorted(built))
    available = set(pending)
    book_sources = {}
    for name in tracked:
        if name.startswith("docs/src/") and name.endswith(".md"):
            source = (root / name).resolve()
            if source.is_relative_to(root):
                chapter = "docs/book/" + name[len("docs/src/"):-3] + ".html"
                canonical = source.relative_to(root).with_suffix(".html").as_posix()
                book_sources[chapter] = canonical
                if name.endswith("/README.md"):
                    book_sources[posixpath.dirname(chapter) + "/index.html"] = canonical
    book_sources["docs/book/index.html"] = "README.html"
    done = set()
    identifiers = {}

    def has_fragment(name: str, fragment: str) -> bool:
        if name not in identifiers:
            path = output / name if name in built else root / name
            identifiers[name] = PublishedHTML(path.read_text(), lambda href, _nav: href).ids
        return unquote(fragment) in identifiers[name]

    def enqueue(name: str) -> bool:
        if name in available:
            return True
        if name not in tracked or not permitted(name):
            return False
        tracked_source(name)
        available.add(name)
        pending.append(name)
        return True

    def rewrite(page: str, href: str, navigation: bool) -> str:
        target = local_target(page, href)
        if target is None:
            return href
        link = urlsplit(href)
        if not link.path:
            return href
        if page in book_sources:
            canonical = local_target(book_sources[page], href)
            if canonical in tracked or canonical in directories or canonical in built:
                target = canonical
        elif page == "docs/book/print.html" and target not in built:
            candidates = {
                posixpath.normpath(posixpath.join(posixpath.dirname(origin), unquote(link.path)))
                for origin in book_sources.values()
            }
            candidates.intersection_update(tracked | directories | built)
            candidates = {name for name in candidates if permitted(name)}
            if link.fragment:
                candidates = {
                    name for name in candidates
                    if name.endswith(".html") and has_fragment(name, link.fragment)
                }
            if len(candidates) == 1:
                target = candidates.pop()
        if target in directories and target not in built:
            for entry in ("index.html", "README.html"):
                if enqueue(f"{target}/{entry}"):
                    destination = posixpath.relpath(target, posixpath.dirname(page)) + "/"
                    return urlunsplit(link._replace(path=destination))
            return urlunsplit((
                "https", "github.com", f"/{repository}/tree/{revision}/{quote(target)}",
                link.query, link.fragment,
            ))
        suffix = Path(target).suffix.lower()
        if suffix in DOCUMENTS | ASSETS and enqueue(target):
            return urlunsplit(link._replace(
                path=quote(posixpath.relpath(target, posixpath.dirname(page)), safe="/"),
            ))
        if navigation and target in tracked:
            return urlunsplit((
                "https", "github.com", f"/{repository}/blob/{revision}/{quote(target)}",
                link.query, link.fragment,
            ))
        return href

    while pending:
        name = pending.popleft()
        if name in done:
            continue
        done.add(name)
        target = output / name
        data = target.read_bytes() if name in built else tracked_source(name).read_bytes()
        if name.endswith((".html", ".htm")):
            source = data.decode("utf-8")
            if name == "docs/book/404.html":
                source = source.replace('<base href="/">', '<base href="./">')
            document = PublishedHTML(source, lambda href, nav: rewrite(name, href, nav))
            data = document.render(source).encode("utf-8")
        elif name.endswith(".css"):
            for match in CSS_URL.finditer(data.decode("utf-8")):
                href = match[2] if match[2] is not None else match[3]
                target_name = local_target(name, href)
                if target_name is not None:
                    enqueue(target_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for name in sorted(done):
        if name.endswith("/README.html"):
            index = output / posixpath.dirname(name) / "index.html"
            if not index.exists():
                index.write_text(redirect("README.html"))
    check(output)
    return len(list(output.rglob("*"))), repository


def check(output: Path) -> None:
    documents = {}
    for page in output.rglob("*.html"):
        name = page.relative_to(output).as_posix()
        document = PublishedHTML(page.read_text(), lambda href, _nav: href)
        documents[name] = document
    errors = []
    for name, document in documents.items():
        for href, navigation in document.links:
            target = local_target(name, href)
            if target is None:
                continue
            link = urlsplit(href)
            path = output / target
            if path.is_dir():
                target = posixpath.join(target, "index.html")
                path = output / target
            suffix = Path(target).suffix.lower()
            if not navigation or suffix in DOCUMENTS | ASSETS:
                if not path.is_file():
                    errors.append(f"{name}: missing documentation or resource: {href}")
                elif link.fragment and target in documents and navigation:
                    visited = set()
                    while documents[target].redirect is not None and target not in visited:
                        visited.add(target)
                        following = local_target(target, documents[target].redirect)
                        if following not in documents:
                            break
                        target = following
                    if unquote(link.fragment) not in documents[target].ids:
                        errors.append(f"{name}: missing section: {href}")
    for page in output.rglob("*.css"):
        name = page.relative_to(output).as_posix()
        for match in CSS_URL.finditer(page.read_text()):
            href = match[2] if match[2] is not None else match[3]
            target = local_target(name, href)
            if target is not None and not (output / target).is_file():
                errors.append(f"{name}: missing CSS resource: {href}")
    if errors:
        raise ValueError("\n".join(errors[:30]) + f"\n{len(errors)} broken publication links")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="absent or empty publication directory")
    args = parser.parse_args(argv)
    try:
        count, repository = publish(ROOT, args.output)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"GitHub Pages publication: {error}", file=sys.stderr)
        return 1
    print(f"GitHub Pages: built and checked {count} entries for {repository} in {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
