from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cga/cgalib"))

import public_html


class PublicHtmlTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="cga-public-html-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source 'checkout'"
        self.home = self.root / "home 'quoted' \"double\""
        self.source.mkdir()
        self.home.mkdir(mode=0o700)
        self.destination = self.home / "public_html/single-machine-mrva"
        self.git("init", "--quiet")
        self.git("config", "user.name", "CGA Test")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "core.hooksPath", "/dev/null")
        for name in public_html.DOCUMENTS:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"committed {name}\n")
        (self.source / "docs/lighttpd-public-html.conf").write_text(
            (ROOT / "docs/lighttpd-public-html.conf").read_text(),
        )
        (self.source / ".gitignore").write_text("ignored.txt\n")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "fixture")

    def git(self, *args, cwd=None):
        return subprocess.check_output(
            ["git", "-C", str(cwd or self.source), *args],
            text=True, stderr=subprocess.PIPE,
        ).strip()

    def invoke(self, source=None):
        output = io.StringIO()
        with (
            tempfile.TemporaryFile(mode="w+") as error,
            mock.patch.object(public_html, "ROOT", source or self.source),
            mock.patch.object(Path, "home", return_value=self.home),
            mock.patch.object(public_html.pwd, "getpwuid") as account,
            redirect_stdout(output),
            redirect_stderr(error),
        ):
            account.return_value.pw_name = "web.user"
            status = public_html.main(["setup"])
            error.flush()
            error.seek(0)
            diagnostics = error.read()
        return status, output.getvalue(), diagnostics

    def test_clones_committed_head_into_absent_or_empty_destination(self):
        (self.source / "docs/cga-help.html").write_text("uncommitted change\n")
        (self.source / "ignored.txt").write_text("not for publication\n")
        home_mode = self.home.stat().st_mode
        status, script, error = self.invoke()
        self.assertEqual(status, 0, error)
        self.assertTrue(script.startswith("#!/usr/bin/env bash\n"))
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.destination),
                         self.git("rev-parse", "HEAD"))
        self.assertEqual((self.destination / "docs/cga-help.html").read_text(),
                         "committed docs/cga-help.html\n")
        self.assertFalse((self.destination / "ignored.txt").exists())
        self.assertFalse((self.destination / "docs/book").exists())
        self.assertEqual(self.home.stat().st_mode, home_mode)
        subprocess.run(["bash", "-n"], input=script, text=True, check=True)
        other = self.home / "empty-publication"
        other.mkdir()
        public_html.clone(self.source, other)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=other),
                         self.git("rev-parse", "HEAD"))

    def test_reuses_existing_clone_without_updating_or_changing_local_files(self):
        self.assertEqual(self.invoke()[0], 0)
        original_head = self.git("rev-parse", "HEAD", cwd=self.destination)
        (self.destination / "index.html").write_text("operator edit\n")
        (self.destination / "operator-note.txt").write_text("keep\n")
        (self.source / "index.html").write_text("new source commit\n")
        self.git("add", "index.html")
        self.git("commit", "--quiet", "-m", "new source")
        before = self.git("status", "--porcelain", cwd=self.destination)
        status, script, error = self.invoke()
        self.assertEqual(status, 0, error)
        self.assertIn("no fetch, pull, or reset", error)
        self.assertTrue(script.startswith("#!/usr/bin/env bash\n"))
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.destination),
                         original_head)
        self.assertEqual(self.git("status", "--porcelain", cwd=self.destination), before)
        self.assertEqual((self.destination / "index.html").read_text(), "operator edit\n")
        self.assertEqual((self.destination / "operator-note.txt").read_text(), "keep\n")

    def test_rejects_non_checkout_and_symlink_without_printing_a_script(self):
        self.destination.parent.mkdir()
        self.destination.symlink_to(self.source, target_is_directory=True)
        status, script, error = self.invoke()
        self.assertEqual(status, 1)
        self.assertEqual(script, "")
        self.assertIn("symlink", error)
        self.destination.unlink()
        self.destination.mkdir()
        note = self.destination / "operator-note.txt"
        note.write_text("keep\n")
        status, script, error = self.invoke()
        self.assertEqual(status, 1)
        self.assertEqual(script, "")
        self.assertIn("cga public-html:", error)
        self.assertEqual(note.read_text(), "keep\n")
        status, script, error = self.invoke(source=self.destination)
        self.assertEqual(status, 1)
        self.assertEqual(script, "")
        self.assertIn("separate directories", error)

    @unittest.skipUnless(shutil.which("lighttpd"), "configuration check requires lighttpd")
    def test_printed_configuration_handles_quoted_paths_and_literal_user_prefix(self):
        status, script, error = self.invoke()
        self.assertEqual(status, 0, error)
        config = script.split("<<'CGA_LIGHTTPD'\n", 1)[1].split("\nCGA_LIGHTTPD\n", 1)[0]
        self.assertIn('var.cga-public-html-url = "/~web.user/"', config)
        path = self.root / "lighttpd.conf"
        path.write_text(
            f"server.document-root = {json.dumps(str(self.root))}\n"
            'server.modules = ("mod_indexfile", "mod_alias", "mod_access")\n'
            + config,
        )
        result = subprocess.run(
            ["lighttpd", "-tt", "-f", str(path)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("WARNING", result.stderr)

    def test_printed_script_refuses_to_replace_operator_configuration(self):
        status, script, error = self.invoke()
        self.assertEqual(status, 0, error)
        config = self.root / "operator.conf"
        config.write_text("# operator settings\n")
        script = script.replace(
            "site_config=/etc/lighttpd/conf-available/50-cga-public-html.conf",
            f"site_config={shlex.quote(str(config))}",
        )
        sudo = 'sudo() { if [ "$1" = cmp ]; then shift; command cmp "$@"; else return 99; fi; }\n'
        result = subprocess.run(
            ["bash"], input=sudo + script, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Existing configuration differs", result.stderr)
        self.assertEqual(config.read_text(), "# operator settings\n")
        self.assertFalse((self.destination / "docs/book").exists())

    def test_printed_script_keeps_an_identical_configuration_symlink(self):
        status, script, error = self.invoke()
        self.assertEqual(status, 0, error)
        configuration = script.split("<<'CGA_LIGHTTPD'\n", 1)[1].split("\nCGA_LIGHTTPD\n", 1)[0]
        target = self.root / "operator.conf"
        target.write_text(configuration + "\n")
        link = self.root / "site.conf"
        link.symlink_to(target)
        script = script.replace(
            "site_config=/etc/lighttpd/conf-available/50-cga-public-html.conf",
            f"site_config={shlex.quote(str(link))}",
        )
        stubs = """\
sudo() {
  case "$1" in
    cmp) shift; command cmp "$@" ;;
    install) printf 'Unexpected config replacement\\n' >&2; return 99 ;;
    *) return 0 ;;
  esac
}
make() { :; }
setfacl() { :; }
find() { :; }
curl() { printf 403; }
"""
        result = subprocess.run(
            ["bash"], input=stubs + script, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(link.is_symlink())
        self.assertEqual(target.read_text(), configuration + "\n")


if __name__ == "__main__":
    unittest.main()
