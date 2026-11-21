from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "docs"))
sys.path.insert(0, str(ROOT / "cga/cgalib"))

import github_io
import github_pages


class GitHubPagesFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="cga-github-pages-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.source = self.base / "source checkout"
        self.source.mkdir()
        self.output = self.base / "web/project"
        self.git("init", "--quiet", "--initial-branch=master")
        self.git("config", "user.name", "CGA Test")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "core.hooksPath", "/dev/null")
        self.git("remote", "add", "origin", "git@github.com:example/project.git")
        files = {
            "index.html": github_pages.redirect("docs/cga-overview.html"),
            "README.md": "# Home\n\n[Guide](cga/guide/README.md#start)\n",
            "README.html": '<h1 id="home">Home</h1><a href="cga/guide/#start">Guide</a>',
            "docs/index.html": github_pages.redirect("cga-overview.html"),
            "docs/cga-overview.html": (
                '<link rel="stylesheet" href="style.css">'
                '<h1 id="overview">Overview</h1>'
                '<a href="cga-help.html">Help</a>'
                '<a href="book/index.html">Book</a>'
                '<a href="../cga/guide/#start">Guide</a>'
                '<a href="../.agent-notes/README.md">LLM</a>'
                '<a href="../cga/guide/source.py#L1">Source</a>'
                '<a href="../examples/">Examples</a>'
            ),
            "docs/cga-help.html": '<h1>Help</h1><a href="cga-overview.html#overview">Overview</a>',
            "docs/style.css": '@import "theme.css"; body { background: url("logo.svg"); }\n',
            "docs/theme.css": '@font-face { font-family: demo; src: url("font.woff2"); }\n',
            "docs/logo.svg": '<svg xmlns="http://www.w3.org/2000/svg"></svg>\n',
            "docs/font.woff2": "font fixture\n",
            "docs/book.toml": '[book]\ntitle = "Example"\nsrc = "src"\n',
            "docs/src/SUMMARY.md": "# Summary\n\n- [Home](overview.md)\n- [Guide](guide.md)\n",
            "docs/src/fonts/fonts.css": "body { font-family: sans-serif; }\n",
            "cga/guide/README.md": (
                "# Guide\n\n## Start\n\n[Home](../../README.md#home)\n\n"
                "[Help](../../docs/cga-help.html)\n"
            ),
            "cga/guide/README.html": '<h1>Guide</h1><h2 id="start">Start</h2>',
            "cga/guide/source.py": 'print("example")\n',
            "examples/query.ql": "// fixed example\n",
            ".agent-notes/README.md": "# Agent instructions\n",
            ".cga/README.md": "# Private workflow\n",
            "tmp/README.md": "# Scratch\n",
            ".env": "PRIVATE_VALUE=not-for-publication\n",
            "cga/web/index.html": "<h1>Live application, not documentation</h1>",
            ".gitignore": "docs/src/ignored*\n",
        }
        for name, content in files.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        (self.source / "docs/src/overview.md").symlink_to("../../README.md")
        (self.source / "docs/src/guide.md").symlink_to("../../cga/guide/README.md")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "fixture")

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.source), *args], text=True, stderr=subprocess.PIPE,
        ).strip()


class GitHubSetupTest(GitHubPagesFixture):
    def invoke(self):
        output, error = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(github_io, "ROOT", self.source),
            redirect_stdout(output), redirect_stderr(error),
        ):
            status = github_io.main(["setup"])
        return status, output.getvalue(), error.getvalue()

    def test_setup_creates_workflow_and_reuses_identical_configuration(self):
        before = self.git("rev-parse", "HEAD")
        status, output, error = self.invoke()
        self.assertEqual(status, 0, error)
        self.assertIn("https://example.github.io/project/", output)
        self.assertIn("Source to GitHub Actions", output)
        self.assertIn("select master", output)
        self.assertEqual(before, self.git("rev-parse", "HEAD"))
        path = self.source / github_io.WORKFLOW
        modified = path.stat().st_mtime_ns
        self.assertEqual(path.read_text(), github_io.workflow("master"))
        self.assertEqual(self.invoke()[0], 0)
        self.assertEqual(path.stat().st_mtime_ns, modified)
        self.assertEqual(
            self.git("status", "--porcelain"),
            "?? .github/",
        )

    def test_setup_refuses_differing_workflow_and_symlink_without_overwriting(self):
        path = self.source / github_io.WORKFLOW
        path.parent.mkdir(parents=True)
        path.write_text("# operator settings\n")
        status, output, error = self.invoke()
        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertIn("existing configuration differs", error)
        self.assertEqual(path.read_text(), "# operator settings\n")
        path.unlink()
        path.symlink_to(self.source / "README.md")
        status, output, error = self.invoke()
        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertIn("symlink", error)
        self.assertTrue(path.is_symlink())

    def test_github_remote_formats_and_user_site_url(self):
        for remote in (
            "https://github.com/example/project.git",
            "ssh://git@github.com/example/project.git",
        ):
            with self.subTest(remote=remote):
                self.git("remote", "set-url", "origin", remote)
                self.assertEqual(github_pages.github_repository(self.source), "example/project")
        self.git("remote", "set-url", "origin", "https://github.com/example/example.github.io.git")
        self.assertIn("https://example.github.io/\n", self.invoke()[1])
        self.git("remote", "set-url", "origin", "/private/local/repository")
        status, output, error = self.invoke()
        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertIn("origin must identify a GitHub repository", error)

    def test_dispatcher_discovery_and_help_are_read_only(self):
        dispatcher = ROOT / "cga/cga"
        before = self.git("status", "--porcelain")
        for args in (("__tools",), ("__subs", "github.io"), ("github.io", "setup", "-h")):
            result = subprocess.run(
                [dispatcher, *args], cwd=self.source,
                check=True, capture_output=True, text=True,
            )
            self.assertIn("github.io" if args == ("__tools",) else "setup", result.stdout)
        self.assertEqual(before, self.git("status", "--porcelain"))


@unittest.skipUnless(shutil.which("mdbook"), "publication checks require mdbook")
class GitHubPublicationTest(GitHubPagesFixture):
    def test_build_filters_files_preserves_links_and_serves_under_project_prefix(self):
        for name in ("docs/src/ignored-note.md", "docs/src/untracked-note.md", "saved-page.html"):
            (self.source / name).write_text("not committed documentation\n")
        github_pages.publish(self.source, self.output)
        for name in (
            ".git/config", ".env", ".cga/README.md", "tmp/README.md",
            "cga/web/index.html", "cga/guide/source.py", "docs/src/overview.md",
            "docs/book/ignored-note.md", "docs/book/untracked-note.md", "saved-page.html",
        ):
            with self.subTest(excluded=name):
                self.assertFalse((self.output / name).exists())
        self.assertTrue((self.output / ".agent-notes/README.md").is_file())
        self.assertFalse(any(path.is_symlink() for path in self.output.rglob("*")))
        source = (self.output / "docs/cga-overview.html").read_text()
        self.assertIn(
            f"https://github.com/example/project/blob/{self.git('rev-parse', 'HEAD')}"
            "/cga/guide/source.py#L1", source,
        )
        self.assertIn("https://github.com/example/project/tree/", source)
        self.assertIn("location.search+location.hash", (self.output / "cga/guide/index.html").read_text())

        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), partial(Handler, directory=str(self.output.parent)),
        )
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            for name in (
                "", "docs/cga-overview.html", "docs/cga-help.html", "cga/guide/",
                "docs/style.css", "docs/theme.css", "docs/logo.svg", "docs/font.woff2",
                ".agent-notes/README.md", "docs/book/index.html", "docs/book/print.html",
            ):
                with self.subTest(published=name):
                    with urlopen(f"http://127.0.0.1:{server.server_port}/project/{name}") as response:
                        self.assertEqual(response.status, 200)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_rejects_nonempty_output_and_missing_documentation_resources(self):
        self.output.mkdir(parents=True)
        note = self.output / "operator-note"
        note.write_text("keep\n")
        with self.assertRaisesRegex(ValueError, "absent or empty"):
            github_pages.publish(self.source, self.output)
        self.assertEqual(note.read_text(), "keep\n")
        note.unlink()
        (self.source / "docs/style.css").write_text('body { background: url("missing.svg"); }\n')
        with self.assertRaisesRegex(ValueError, "missing CSS resource"):
            github_pages.publish(self.source, self.output)

    def test_rejects_external_resource_symlinks(self):
        outside = self.base / "outside.svg"
        outside.write_text("not a repository asset\n")
        asset = self.source / "docs/logo.svg"
        asset.unlink()
        asset.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "external or untracked symlink target"):
            github_pages.publish(self.source, self.output)

    def test_rejects_root_absolute_urls_and_missing_sections(self):
        page = self.source / "docs/cga-overview.html"
        original = page.read_text()
        for number, (link, error) in enumerate((
            ("/docs/cga-help.html", "root-absolute URL"),
            ("cga-help.html#missing-section", "missing section"),
        )):
            with self.subTest(link=link):
                page.write_text(original + f'<a href="{link}">Invalid link</a>')
                with self.assertRaisesRegex(ValueError, error):
                    github_pages.publish(self.source, self.base / f"invalid-site-{number}")


if __name__ == "__main__":
    unittest.main()
