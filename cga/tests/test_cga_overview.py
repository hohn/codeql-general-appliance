from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.parse import unquote, urlsplit
from urllib.request import urlopen


COLLECTION = Path(__file__).resolve().parents[1]
ROOT = COLLECTION.parent
OVERVIEW = ROOT / "docs/cga-overview.html"
LEGACY = ROOT / "docs/cga-sample-05.html"
sys.path.insert(0, str(COLLECTION / "cgalib"))

import sample_help


@dataclass
class Element:
    tag: str
    attrs: dict[str, str]
    children: list[Element | str] = field(default_factory=list)

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Element):
                yield from child.walk()

    def text(self) -> str:
        return "".join(
            child.text() if isinstance(child, Element) else child
            for child in self.children
        )


class Document(HTMLParser):
    VOID = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("document", {})
        self.stack = [self.root]
        self.feed(source)
        self.close()
        self.elements = list(self.root.walk())
        self.ids = Counter(
            element.attrs["id"] for element in self.elements
            if "id" in element.attrs
        )

    def handle_starttag(self, tag, attrs) -> None:
        element = Element(tag, {key: value or "" for key, value in attrs})
        self.stack[-1].children.append(element)
        if tag not in self.VOID:
            self.stack.append(element)

    def handle_startendtag(self, tag, attrs) -> None:
        self.stack[-1].children.append(
            Element(tag, {key: value or "" for key, value in attrs}),
        )

    def handle_endtag(self, tag) -> None:
        if self.stack[-1].tag != tag:
            raise AssertionError(f"Unexpected </{tag}> inside <{self.stack[-1].tag}>")
        self.stack.pop()

    def handle_data(self, data) -> None:
        self.stack[-1].children.append(data)

    def commands(self) -> dict[str, str]:
        commands = {}
        for row in self.elements:
            if "command-row" not in row.attrs.get("class", "").split():
                continue
            code = next(element for element in row.walk() if element.tag == "code")
            button = next(
                element for element in row.walk() if "data-copy" in element.attrs
            )
            label = button.attrs["aria-label"]
            if label in commands:
                raise AssertionError(f"Duplicate copy control: {label}")
            commands[label] = code.text().strip()
        return commands


def shell_blocks(path: Path) -> list[str]:
    return re.findall(r"```sh\n(.*?)```", path.read_text(), re.DOTALL)


class CgaOverviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.page = Document(OVERVIEW.read_text())
        cls.commands = cls.page.commands()

    def test_self_contained_pages_and_local_links(self) -> None:
        documents = {
            OVERVIEW: self.page,
            LEGACY: Document(LEGACY.read_text()),
            ROOT / "index.html": Document((ROOT / "index.html").read_text()),
            ROOT / "docs/index.html": Document((ROOT / "docs/index.html").read_text()),
        }
        for path, document in list(documents.items()):
            with self.subTest(page=path.name):
                self.assertTrue(all(count == 1 for count in document.ids.values()))
                self.assertEqual(len(document.stack), 1, "Unclosed HTML elements")
                for element in document.elements:
                    self.assertNotIn(element.tag, {"iframe", "object", "embed"})
                    if element.tag in {"script", "link", "img", "source"}:
                        self.assertNotIn("src", element.attrs, "Keep assets inline")
                        self.assertNotIn("href", element.attrs, "Keep assets inline")
                    if element.tag != "a":
                        continue
                    link = element.attrs.get("href", "")
                    target = urlsplit(link)
                    if target.scheme:
                        continue
                    destination = (
                        path.parent / unquote(target.path) if target.path else path
                    ).resolve()
                    if destination == ROOT / "docs/book/index.html":
                        continue  # The reference book is built separately.
                    self.assertTrue(destination.is_file(), link)
                    if target.fragment and destination.suffix == ".html":
                        if destination not in documents:
                            documents[destination] = Document(destination.read_text())
                        self.assertIn(
                            unquote(target.fragment), documents[destination].ids, link,
                        )

    def test_readmes_lead_with_the_same_reading_order(self) -> None:
        expected = [
            OVERVIEW,
            ROOT / "docs/cga-help.html",
            ROOT / "docs/book/index.html",
        ]
        for path in (ROOT / "README.html", ROOT / "docs/README.html",
                     COLLECTION / "README.html"):
            with self.subTest(page=path.relative_to(ROOT)):
                links = [
                    (path.parent / unquote(urlsplit(element.attrs["href"]).path)).resolve()
                    for element in Document(path.read_text()).elements
                    if element.tag == "a"
                    and element.attrs.get("href", "").endswith(".html")
                ]
                self.assertEqual(links[:3], expected)

    def test_sample_steps_match_executable_recipe_order(self) -> None:
        actual = [
            command for command in self.commands.values()
            if re.fullmatch(r"cga h s 05 \d{2} r", command)
        ]
        self.assertEqual(
            actual, [f"cga h s 05 {step.number} r" for step in sample_help.STEPS],
        )

    def test_installation_commands_match_canonical_sources(self) -> None:
        blocks = shell_blocks(COLLECTION / "README.md")
        dispatcher = next(block for block in blocks if block.startswith("repo_root="))
        self.assertEqual(
            self.commands["Copy CGA dispatcher installation commands"],
            dispatcher.strip().replace(
                "cga --help", 'export PATH="$HOME/.local/bin:$PATH"\ncga --help',
            ),
        )
        completion = next(block for block in blocks if block.startswith("source "))
        self.assertEqual(
            self.commands["Copy Bash completion command"], completion.strip(),
        )
        for distribution, label in (
            ("ubuntu-noble", "Copy Ubuntu installation commands"),
            ("debian-sid", "Copy Debian installation commands"),
        ):
            with self.subTest(distribution=distribution):
                commands = [
                    block.strip()
                    for block in shell_blocks(ROOT / "vm-setup" / distribution / "README.md")
                    if re.fullmatch(
                        rf"\./vm-setup/{distribution}/install-dependencies\.sh"
                        r"( --list)?\s*", block,
                    )
                ]
                self.assertEqual(len(commands), 2)
                self.assertEqual(self.commands[label], "\n".join(commands))
        self.assertEqual(
            self.commands["Copy sample inspection commands"],
            "cga help sample 05\ncga h s 05 00",
        )

    def test_displayed_commands_have_valid_shell_syntax(self) -> None:
        for label, command in self.commands.items():
            with self.subTest(control=label):
                result = subprocess.run(
                    ["bash", "-n"], input=command, text=True,
                    capture_output=True, timeout=5,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(
        shutil.which("chromium") and shutil.which("node"),
        "offline browser checks require Chromium and Node",
    )
    def test_offline_browser_behavior(self) -> None:
        websocket = subprocess.run(
            ["node", "-p", "typeof WebSocket"],
            check=True, capture_output=True, text=True, timeout=10,
        )
        if websocket.stdout.strip() != "function":
            self.skipTest("browser checks require Node's built-in WebSocket")
        with tempfile.TemporaryDirectory(prefix="cga-overview-") as directory:
            profile = Path(directory) / "browser"
            with tempfile.TemporaryFile(mode="w+") as log:
                browser = subprocess.Popen(
                    [
                        "chromium", "--headless", "--disable-gpu",
                        "--disable-background-networking", "--disable-sync",
                        "--no-first-run", "--no-sandbox", "--disable-dev-shm-usage",
                        "--remote-debugging-address=127.0.0.1",
                        "--remote-debugging-port=0",
                        f"--user-data-dir={profile}", "about:blank",
                    ],
                    stdout=log, stderr=log,
                )
                try:
                    active = profile / "DevToolsActivePort"
                    deadline = time.monotonic() + 15
                    while not active.exists():
                        if browser.poll() is not None or time.monotonic() >= deadline:
                            log.seek(0)
                            self.fail(f"Chromium failed to become ready:\n{log.read()}")
                        time.sleep(0.05)
                    port = active.read_text().splitlines()[0]
                    with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=5) as response:
                        endpoint = json.load(response)["webSocketDebuggerUrl"]
                    result = subprocess.run(
                        [
                            "node", COLLECTION / "tests/overview-browser.mjs",
                            endpoint, OVERVIEW.as_uri(), LEGACY.as_uri(),
                        ],
                        input=json.dumps(self.commands), capture_output=True,
                        text=True, timeout=90,
                    )
                    self.assertEqual(
                        result.returncode, 0, result.stdout + result.stderr,
                    )
                finally:
                    if browser.poll() is None:
                        browser.terminate()
                    try:
                        browser.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        browser.kill()
                        browser.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
