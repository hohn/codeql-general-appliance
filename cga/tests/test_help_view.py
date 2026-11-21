from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock


COLLECTION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(COLLECTION / "cgalib"))

import help_view
import tutorial_help
from vid_registry import REGISTRY, reference


class HelpViewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="cga-help-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.workflow = cls.root / "workflow"
        cls.workflow.mkdir()
        cls.environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("CGA_", "CGAST_", "CGACTL_", "MRVA_"))
        }
        cls.environment.update({
            "PYTHON_COLORS": "0",
            "CGA_TMPDIR": str(cls.root / "scratch"),
            "CGA_RUN_DIR": str(cls.root / "services"),
        })
        for args in (("init",), ("chain", "start", "--name", "help-export")):
            subprocess.run(
                [COLLECTION / "cga", *args], cwd=cls.workflow,
                env=cls.environment, check=True, capture_output=True, text=True,
            )
        cls.before = cls.workflow_files()
        cls.output = cls.root / "help.html"
        cls.result = subprocess.run(
            [COLLECTION / "cga", "help", "--export", cls.output],
            cwd=cls.workflow, env=cls.environment,
            capture_output=True, text=True, timeout=120, check=True,
        )
        cls.document = cls.output.read_text(encoding="utf-8")
        payload = re.search(
            r'<script id="help-data" type="application/json">(.*?)</script>',
            cls.document, re.DOTALL,
        )
        if payload is None:
            raise AssertionError("export has no embedded help data")
        cls.model = json.loads(payload[1])

    @classmethod
    def workflow_files(cls) -> dict[Path, bytes]:
        return {
            path.relative_to(cls.workflow): path.read_bytes()
            for path in cls.workflow.rglob("*") if path.is_file()
        }

    def test_export_contains_real_help_and_leaves_workflow_unchanged(self) -> None:
        self.assertEqual(self.result.stdout.strip(), str(self.output))
        self.assertEqual(self.before, self.workflow_files())
        self.assertEqual(
            {path.name for path in self.root.iterdir()}, {"workflow", "help.html"},
        )
        page = self.model["pages"]["cga init"]
        actual = subprocess.run(
            [COLLECTION / "cga", "init", "-h"], env=self.environment,
            check=True, capture_output=True, text=True,
        )
        self.assertEqual(
            page["sections"], help_view.split_sections(actual.stdout + actual.stderr),
        )
        self.assertNotRegex(self.document, r'<(?:script|link)[^>]+(?:src|href)=')
        self.assertNotIn("{{", self.document)
        identifiers = [node["id"] for node in self.model["tree"]]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertEqual(identifiers.count("cga view"), 1)
        for node in self.model["tree"]:
            self.assertIn(node["id"], self.model["pages"])
            for child in self.model["pages"][node["id"]]["children"]:
                self.assertIn(child["id"], self.model["pages"])
        self.assertNotIn("cga uv serve", self.model["pages"])

    def test_outlines_sort_commands_and_share_task_links(self) -> None:
        tree = self.model["tree"]
        self.assertEqual(tree[0]["id"], "cga")
        labels = [node["label"] for node in tree[1:]]
        self.assertEqual(labels, sorted(labels, key=str.casefold))
        groups = {
            group["label"]: {node["id"] for node in group["commands"]}
            for group in self.model["task_groups"]
        }
        self.assertEqual(list(groups), [
            "Create databases", "Write and prepare queries",
            "Apply queries", "Review results",
        ])
        self.assertIn("cga db", groups["Create databases"])
        self.assertIn("cga cc", groups["Write and prepare queries"])
        self.assertIn("cga mr", groups["Apply queries"])
        self.assertIn("cga si", groups["Review results"])
        self.assertIn("cga ql", groups["Write and prepare queries"] & groups["Apply queries"])
        for group in self.model["task_groups"]:
            for node in group["commands"]:
                self.assertIn(node, tree)

    def test_start_here_embeds_the_authoritative_cli_walkthrough(self) -> None:
        self.assertEqual(
            [node["label"] for node in self.model["start_here"][:7]],
            ["Visual overview", "Reference manual", "CGA overview",
             "getting started", "bash example -- sqlite tutorial", "sample 05",
             "single-user MRVA flow"],
        )
        output = subprocess.run(
            [COLLECTION / "cga", "-hs"], env=self.environment,
            check=True, capture_output=True, text=True,
        )
        self.assertEqual(
            self.model["pages"]["cga help getting-started"]["sections"],
            help_view.split_sections(output.stdout),
        )
        for number in ("00", "08", "13", "18", "20"):
            self.assertIn(f"cga help sample 05 {number}", self.model["pages"])
        self.assertEqual(
            [link["label"] for link in self.model["pages"]["cga help sample 05"]["children"]],
            [step.number for step in help_view.sample_help.STEPS],
        )

    def test_overview_matches_cli_and_is_read_only(self) -> None:
        before_entries = {path.name for path in self.root.iterdir()}
        page = self.model["pages"]["cga help overview"]
        self.assertIn("Overview", [section["heading"] for section in page["sections"]])
        self.assertIn("Running", [section["heading"] for section in page["sections"]])
        for args in (
            ("help", "overview"), ("help", "overview", "-h"),
            ("help", "overview", "--help"), ("h", "overview"),
        ):
            with self.subTest(arguments=args):
                result = subprocess.run(
                    [COLLECTION / "cga", *args], cwd=self.workflow,
                    env=self.environment, check=True, capture_output=True, text=True,
                )
                self.assertEqual(result.stderr, "")
                self.assertEqual(page["sections"], help_view.split_sections(result.stdout))
        discovery = subprocess.run(
            [COLLECTION / "cga", "__subs", "help"],
            env=self.environment, check=True, capture_output=True, text=True,
        )
        self.assertIn("overview", discovery.stdout.split())
        for args in (
            ("help", "overview", "--unknown"),
            ("help", "--export", str(self.root / "bad.html"), "overview"),
        ):
            with self.subTest(arguments=args):
                result = subprocess.run(
                    [COLLECTION / "cga", *args], cwd=self.workflow,
                    env=self.environment, capture_output=True, text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("error:", result.stderr)
        self.assertFalse((self.root / "bad.html").exists())
        self.assertEqual(self.before, self.workflow_files())
        self.assertEqual(before_entries, {path.name for path in self.root.iterdir()})

    def test_document_links_resolve_from_the_export_directory(self) -> None:
        tutorials = {
            link["label"]: (self.output.parent / link["href"]).resolve()
            for link in self.model["tutorial_documents"]
        }
        book = tutorials.pop("Reference manual")
        self.assertEqual(book, tutorial_help.ROOT / "docs/book/index.html")
        self.assertEqual(
            [
                (self.output.parent / link["href"]).resolve()
                for link in self.model["start_here"][:2]
            ],
            [tutorial_help.ROOT / "docs/cga-overview.html", book],
        )
        self.assertEqual(tutorials, {
            tutorial.label: (tutorial_help.ROOT / tutorial.source).with_suffix(".html")
            for tutorial in tutorial_help.TUTORIALS
        })
        for target in tutorials.values():
            self.assertTrue(target.is_file(), target)
            self.assertTrue(target.with_suffix(".md").is_file(), target)
        self.assertEqual(len(self.model["system_tests"]), 1)
        system_tests = (
            self.output.parent / self.model["system_tests"][0]["href"]
        ).resolve()
        self.assertEqual(system_tests, COLLECTION / "system-tests/README.html")
        self.assertTrue(system_tests.is_file())
        llm_links = self.model["llm_start_here"]
        self.assertEqual(llm_links[0]["label"], "LLM exploration guide")
        self.assertIn("cga llm context", [
            link["id"] for link in llm_links if "id" in link
        ])
        for child in self.model["pages"]["cga llm context"]["children"]:
            self.assertIn(child["id"], self.model["pages"])
        for link in llm_links:
            if "href" in link:
                self.assertTrue((self.output.parent / link["href"]).is_file(), link)
            else:
                self.assertIn(link["id"], self.model["pages"])

    def test_help_references_are_permanent_and_pin_document_content(self) -> None:
        entries = self.model["references"]["elements"]
        self.assertTrue(entries)
        help_roots = {entry["vid"] for entry in entries}
        other_roots = {entry["vid"] for entry in REGISTRY if not entry["selectors"].get("help")}
        self.assertFalse(help_roots & other_roots)
        for entry in entries:
            self.assertRegex(entry["vid"], r"^:[0-9a-z]{3}$")
            self.assertFalse(entry["selectors"]["bench"])
            self.assertFalse(entry["selectors"]["unified"])
        targets = self.model["references"]["targets"]
        page = reference("help-pages", "help", "bash-tutorial-sql", "mrva")
        self.assertEqual(targets[page]["command"], "cga help bash-tutorial-sql mrva")
        self.assertEqual(targets[page + ",section,walkthrough"]["section"], "Walkthrough")
        raw = help_view.HelpModel(
            generated_at="first", start_here=[], llm_start_here=[], tutorial_documents=[],
            system_tests=[], tree=[], task_groups=[], pages={"cga": self.model["pages"]["cga"]},
        )
        def generation(value):
            document = help_view.render_document(value)
            return json.loads(re.search(
                r'<script id="help-data" type="application/json">(.*?)</script>',
                document, re.S,
            )[1])["references"]["generation"]
        original = generation(raw)
        raw["generated_at"] = "later"
        self.assertEqual(generation(raw), original)
        changed = {**raw, "pages": {
            "cga": {**raw["pages"]["cga"], "sections": [
                {"heading": "Name", "text": "changed document"},
            ]},
        }}
        self.assertNotEqual(generation(changed), original)

    def test_tutorials_preserve_commands_and_do_not_execute(self) -> None:
        for tutorial in tutorial_help.TUTORIALS:
            with self.subTest(tutorial=tutorial.name):
                source = tutorial_help.ROOT / tutorial.source
                original = source.with_suffix(".html").read_bytes()
                bodies = re.split(r"(?m)^#{2,3} (.+)\n", source.read_text())[2::2]
                command = f"cga help {tutorial.name}"
                self.assertIn(command, [
                    node["id"] for node in self.model["start_here"] if "id" in node
                ])
                overview = self.model["pages"][command]
                self.assertEqual(
                    [child["match"] for child in overview["children"]],
                    [name for name, _title in tutorial.chapters],
                )
                result = subprocess.run(
                    [COLLECTION / "cga", "-C", self.workflow, "help", tutorial.name],
                    env=self.environment, check=True, capture_output=True, text=True,
                )
                self.assertEqual(
                    help_view.split_sections(result.stdout), overview["sections"],
                )
                for (name, _title), body in zip(tutorial.chapters, bodies):
                    page = self.model["pages"][f"{command} {name}"]
                    walkthrough = next(
                        section["text"] for section in page["sections"]
                        if section["heading"] == "Walkthrough"
                    )
                    for language, commands in re.findall(
                        r"```([^\n]*)\n(.*?)\n```", body, re.S,
                    ):
                        self.assertIn(commands, textwrap.dedent(walkthrough))
                        if (
                            tutorial.name == "bash-tutorial-sql"
                            and language in ("sh", "bash")
                        ):
                            subprocess.run(
                                ["bash", "-n"], input=commands, text=True,
                                check=True, capture_output=True,
                            )
                    result = subprocess.run(
                        [COLLECTION / "cga", "-C", self.workflow, "help",
                         tutorial.name, name],
                        env=self.environment, check=True, capture_output=True, text=True,
                    )
                    self.assertEqual(
                        help_view.split_sections(result.stdout), page["sections"],
                    )
                self.assertEqual(self.before, self.workflow_files())
                self.assertEqual(original, source.with_suffix(".html").read_bytes())
                for args in (
                    (tutorial.name, tutorial.chapters[0][0], "run"),
                    (tutorial.name, tutorial.chapters[0][0], "--unknown"),
                    ("--export", str(self.root / "bad.html"), tutorial.name),
                ):
                    result = subprocess.run(
                        [COLLECTION / "cga", "help", *args], env=self.environment,
                        capture_output=True, text=True,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("error:", result.stderr)
        self.assertFalse((self.root / "bad.html").exists())
        self.assertEqual(self.before, self.workflow_files())

    def test_tutorial_completion_and_source_errors(self) -> None:
        discovery = subprocess.run(
            [COLLECTION / "cga", "__subs", "help"],
            env=self.environment, check=True, capture_output=True, text=True,
        )
        for tutorial in tutorial_help.TUTORIALS:
            with self.subTest(tutorial=tutorial.name):
                self.assertIn(tutorial.name, discovery.stdout.split())
                for depth in (3, 4):
                    result = subprocess.run(
                        ["bash", "-c",
                         'source "$1"; COMP_WORDS=("$2" help "$3" ""); '
                         'COMP_CWORD="$4"; _cga; printf "%s\\n" "${COMPREPLY[@]}"',
                         "_", str(COLLECTION / "completions/cga.bash"),
                         str(COLLECTION / "cga"), tutorial.name, str(depth)],
                        env=self.environment, check=True, capture_output=True, text=True,
                    )
                    expected = {"-h", "--help"}
                    if depth == 3:
                        expected |= {name for name, _title in tutorial.chapters}
                    self.assertEqual(set(result.stdout.splitlines()), expected)
                with mock.patch.object(
                    Path, "read_text", return_value="## Unexpected chapter\n",
                ):
                    with self.assertRaisesRegex(ValueError, "headings changed"):
                        tutorial_help.content(tutorial)

    def test_tutorial_headings_inside_fences_are_not_chapters(self) -> None:
        tutorial = tutorial_help.Tutorial(
            "fixture", "fixture", "fixture.md", "fixture", (("read", "Read"),),
        )
        markdown = (
            "# Fixture\n\n## Read\n\n```text\n## Not a chapter\n"
            "`literal` **literal** [literal](target)\n```\n\n"
            "Return to [Read](#read).\n"
        )
        with mock.patch.object(Path, "read_text", return_value=markdown):
            _overview, chapters = tutorial_help.content(tutorial)
        self.assertIn(
            "## Not a chapter\n`literal` **literal** [literal](target)", chapters["read"],
        )
        self.assertIn("Read (cga help fixture read)", chapters["read"])
        with mock.patch.object(Path, "read_text", return_value=markdown[:-1] + "\n```sh"):
            with self.assertRaisesRegex(ValueError, "unclosed code fence"):
                tutorial_help.content(tutorial)

    def test_root_help_alias_remains_unchanged(self) -> None:
        outputs = [
            subprocess.run(
                [COLLECTION / "cga", option], check=True,
                env=self.environment, capture_output=True, text=True,
            ).stdout
            for option in ("help", "-h")
        ]
        self.assertEqual(*outputs)
        sample = subprocess.run(
            [COLLECTION / "cga", "help", "sample-05"],
            check=True, env=self.environment, capture_output=True, text=True,
        )
        self.assertEqual(
            help_view.split_sections(sample.stdout),
            self.model["pages"]["cga help sample 05"]["sections"],
        )

    def test_section_capture_preserves_inline_synopsis_and_custom_headings(self) -> None:
        sections = help_view.split_sections(
            "Name:\n  cga example - example help\n\n"
            "Synopsis: cga example [-h]\n"
            "Selection Filters:\n  --language LANGUAGE\n"
        )
        self.assertEqual(sections, [
            {"heading": "Name", "text": "  cga example - example help"},
            {"heading": "Synopsis", "text": "cga example [-h]"},
            {"heading": "Selection Filters", "text": "  --language LANGUAGE"},
        ])
        with self.assertRaisesRegex(ValueError, "unrecognized help preamble"):
            help_view.split_sections("Unexpected error\nName:\n  cga")

    def test_failed_help_capture_is_explicit_and_preserves_existing_export(self) -> None:
        result = subprocess.CompletedProcess(
            args=["cga", "init", "-h"], returncode=2, stdout="",
            stderr="test help failure",
        )
        with mock.patch.object(help_view.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(ValueError, "test help failure"):
                help_view.capture_help(("init",))
        destination = self.root / "existing.html"
        destination.write_text("previous export", encoding="utf-8")
        try:
            with mock.patch.object(
                help_view, "collect_help", side_effect=ValueError("test help failure"),
            ):
                with self.assertRaisesRegex(ValueError, "test help failure"):
                    help_view.export(destination)
            self.assertEqual(destination.read_text(), "previous export")
        finally:
            destination.unlink()

    def test_embedded_help_cannot_terminate_the_data_script(self) -> None:
        payload = '</script><script>window.helpInjected = true</script><img src=x>'
        model = help_view.HelpModel(
            generated_at="test", tree=[self.model["tree"][0]], task_groups=[], start_here=[],
            llm_start_here=[], tutorial_documents=[], system_tests=[],
            pages={"cga": help_view.Page(
                command="cga",
                sections=[help_view.Section(heading="Description", text=payload)],
                children=[],
            )},
        )
        document = help_view.render_document(model)
        self.assertNotIn(payload, document)
        embedded = re.search(
            r'<script id="help-data" type="application/json">(.*?)</script>',
            document, re.DOTALL,
        )
        self.assertIsNotNone(embedded)
        self.assertEqual(
            json.loads(embedded[1])["pages"]["cga"]["sections"][0]["text"], payload,
        )

    @unittest.skipUnless(
        shutil.which("chromium") and shutil.which("node"),
        "offline browser checks require Chromium and Node",
    )
    def test_offline_navigation_scrolling_resizing_and_text_safety(self) -> None:
        websocket = subprocess.run(
            ["node", "-p", "typeof WebSocket"],
            check=True, capture_output=True, text=True,
        )
        if websocket.stdout.strip() != "function":
            self.skipTest("browser checks require Node's built-in WebSocket")
        profile = self.root / "browser"
        browser = subprocess.Popen(
            [
                "chromium", "--headless", "--disable-gpu",
                "--disable-background-networking", "--disable-sync", "--no-first-run",
                "--remote-debugging-port=0", f"--user-data-dir={profile}", "about:blank",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

        def stop() -> None:
            if browser.poll() is None:
                browser.terminate()
            browser.wait(timeout=10)

        self.addCleanup(stop)
        active = profile / "DevToolsActivePort"
        deadline = time.monotonic() + 10
        while not active.exists():
            if browser.poll() is not None or time.monotonic() >= deadline:
                self.fail("Chromium failed to become ready")
            time.sleep(0.05)
        port, socket = active.read_text().splitlines()
        injection = self.root / "injection.html"
        payload = '</script><script>window.helpInjected=true</script><img src=x>'
        injection.write_text(
            help_view.render_document(help_view.HelpModel(
                generated_at="test", tree=[self.model["tree"][0]], task_groups=[], start_here=[],
                llm_start_here=[], tutorial_documents=[], system_tests=[],
                pages={"cga": help_view.Page(
                    command="cga",
                    sections=[help_view.Section(heading="Description", text=payload)],
                    children=[],
                )},
            )),
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                "node", COLLECTION / "tests" / "help-browser.mjs",
                f"ws://127.0.0.1:{port}{socket}",
                self.output.as_uri(), injection.as_uri(),
            ],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
