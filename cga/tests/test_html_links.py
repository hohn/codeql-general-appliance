from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "docs"))

from html_links import llm_source, rewrite_html


class HtmlLinksTest(unittest.TestCase):
    def test_local_links_preserve_queries_fragments_and_markup(self) -> None:
        source = (
            '<a title="example href=\'other.md\'"\n'
            ' href="../a%20guide.md?mode=1&amp;view=2#the-section">guide.md</a>\r\n'
            "<a HREF='reference.md'>Reference</a><a href=another.md>Another</a>"
        )
        expected = source.replace("a%20guide.md?", "a%20guide.html?").replace(
            "HREF='reference.md'", "HREF='reference.html'",
        ).replace("href=another.md", "href=another.html")
        actual = rewrite_html(source, ROOT / "docs/example.html")
        self.assertEqual(actual, expected)
        self.assertEqual(rewrite_html(actual, ROOT / "docs/example.html"), actual)

    def test_external_links_and_non_navigation_content_are_unchanged(self) -> None:
        source = (
            '<a href="https://github.com/owner/repo/blob/main/README.md">GitHub</a>'
            '<a href="//example.com/README.md">External</a>'
            '<a href="mailto:person@example.md">Mail</a>'
            '<a href="?source=README.md">Query</a><a href="#README.md">Fragment</a>'
            '<img src="diagram.md"><code>&lt;a href="example.md"&gt;</code>'
            '<!-- <a href="comment.md"> -->'
            '<script>const example = \'<a href="script.md">\';</script>'
        )
        self.assertEqual(rewrite_html(source, ROOT / "docs/example.html"), source)

    def test_llm_sources_remain_source_links(self) -> None:
        source = (
            '<a href="../AGENTS.md">Agent instructions</a>'
            '<a href="../.agent-notes/documentation.md#contract">Agent notes</a>'
            '<a href="cga-help-llm.org">LLM guide</a>'
            '<a href="../cga/README.md">Human reference</a>'
        )
        expected = source.replace("../cga/README.md", "../cga/README.html")
        self.assertEqual(rewrite_html(source, ROOT / "docs/example.html"), expected)
        for page in (ROOT / "AGENTS.html", ROOT / ".agent-notes/documentation.html"):
            with self.subTest(page=page):
                self.assertEqual(rewrite_html(source, page), source)

    def test_command_line_check_and_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            page = Path(directory) / "example.html"
            source = b'<a href="guide.md#start">Guide</a>\r\n'
            page.write_bytes(source)
            command = [sys.executable, ROOT / "docs/html_links.py"]
            checked = subprocess.run(
                [*command, "--check", page], capture_output=True, text=True, timeout=5,
            )
            self.assertEqual(checked.returncode, 1)
            self.assertIn("must target HTML", checked.stderr)
            self.assertEqual(page.read_bytes(), source)
            subprocess.run([*command, page], check=True, timeout=5)
            self.assertEqual(
                page.read_bytes(), source.replace(b"guide.md", b"guide.html"),
            )
            subprocess.run([*command, "--check", page], check=True, timeout=5)


class DocumentLinks(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__()
        self.ids = set()
        self.links = []
        self.resources = []
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, attrs) -> None:
        attributes = dict(attrs)
        if "id" in attributes:
            self.ids.add(attributes["id"])
        if tag == "a" and attributes.get("href"):
            self.links.append(attributes["href"])
        if tag == "link" and attributes.get("href"):
            self.resources.append(attributes["href"])
        if tag in ("script", "img") and attributes.get("src"):
            self.resources.append(attributes["src"])


class GeneratedHtmlLinksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        paths = subprocess.check_output(
            ["git", "ls-files", "-z", "--", "*.html"], cwd=ROOT, text=True,
        ).split("\0")
        cls.pages = {}
        for name in filter(None, paths):
            page = ROOT / name
            source = page.read_bytes().decode("utf-8")
            cls.pages[page] = source, DocumentLinks(source)

    def test_tracked_html_has_no_human_markdown_links(self) -> None:
        for page, (source, _) in self.pages.items():
            with self.subTest(page=page.relative_to(ROOT)):
                self.assertEqual(
                    rewrite_html(source, page), source,
                    f"{page}: regenerate human document links as HTML",
                )

    def test_local_html_destinations_and_fragments_exist(self) -> None:
        for page, (_, document) in self.pages.items():
            if llm_source(page.with_suffix(".md")):
                continue
            for href in document.links:
                link = urlsplit(href)
                if link.scheme or link.netloc or not link.path.endswith(".html"):
                    continue
                target = (page.parent / unquote(link.path)).resolve()
                if target.is_relative_to(ROOT / "docs/book"):
                    continue  # The optional mdBook output has its own build.
                with self.subTest(page=page.relative_to(ROOT), link=href):
                    self.assertTrue(
                        target in self.pages, f"Missing tracked HTML target: {target}",
                    )
                    if link.fragment:
                        self.assertIn(
                            unquote(link.fragment), self.pages[target][1].ids,
                            "Missing destination section",
                        )


@unittest.skipUnless(shutil.which("mdbook"), "reference book checks require mdbook")
class BookPublicationTest(unittest.TestCase):
    def test_front_page_links_and_resources_are_built(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            built = subprocess.run(
                ["mdbook", "build", "--dest-dir", directory], cwd=ROOT / "docs",
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            output = Path(directory)
            document = DocumentLinks((output / "index.html").read_text())
            for href in document.links + document.resources:
                link = urlsplit(href)
                if link.scheme or link.netloc or not link.path:
                    continue
                with self.subTest(link=href):
                    target = output / unquote(link.path)
                    self.assertTrue(target.is_file(), f"Missing book target: {href}")


if __name__ == "__main__":
    unittest.main()
