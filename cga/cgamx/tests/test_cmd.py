from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
CGA_ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(CGA_ROOT / "cgalib"))

from cgamx import cmd  # noqa: E402


class ParseBodyTest(unittest.TestCase):
    def test_argv_list(self) -> None:
        self.assertEqual(cmd._parse_body(b'{"argv": ["cgasi", "view"]}'),
                         ["cgasi", "view"])

    def test_command_string_shlex(self) -> None:
        self.assertEqual(
            cmd._parse_body(b'{"command": "cgasi view --uri \'\\\\.c$\'"}'),
            ["cgasi", "view", "--uri", "\\.c$"])

    def test_bare_command_line(self) -> None:
        self.assertEqual(cmd._parse_body(b"cgasi view --erc 40"),
                         ["cgasi", "view", "--erc", "40"])

    def test_empty(self) -> None:
        self.assertEqual(cmd._parse_body(b"  "), [])


class WhitelistTest(unittest.TestCase):
    def test_non_cga_program_refused(self) -> None:
        ok, code, human = cmd.run_argv(["ls", "-l"])
        self.assertFalse(ok)
        self.assertEqual(code, 2)
        self.assertIn("only cga* binaries", human)

    def test_cga_name_but_not_on_path_refused(self) -> None:
        ok, code, human = cmd.run_argv(["cganope-does-not-exist"])
        self.assertFalse(ok)
        self.assertEqual(code, 2)

    def test_empty_argv(self) -> None:
        ok, code, _ = cmd.run_argv([])
        self.assertFalse(ok)
        self.assertEqual(code, 2)


class SessionThreadingTest(unittest.TestCase):
    """run_argv runs a fake cga* binary as a CGAST filter over the session."""

    def _make_fake_bin(self, tmp: Path, name: str, body: str) -> None:
        p = tmp / name
        p.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
        p.chmod(0o755)

    def test_success_replaces_session_with_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            session = tmp / "session.json"
            session.write_text('{"a": 1}\n', encoding="utf-8")
            bindir = tmp / "bin"
            bindir.mkdir()
            # A cga* filter that adds a key to whatever CGAST it reads on stdin.
            self._make_fake_bin(bindir, "cgafake", (
                "import json, sys\n"
                "obj = json.load(sys.stdin)\n"
                "obj['b'] = 2\n"
                "sys.stderr.write('did the thing\\n')\n"
                "json.dump(obj, sys.stdout)\n"
            ))
            env = {"CGA_SESSION": str(session),
                   "PATH": str(bindir) + os.pathsep + os.environ["PATH"]}
            with mock.patch.dict(os.environ, env, clear=False):
                ok, code, human = cmd.run_argv(["cgafake"])
            self.assertTrue(ok)
            self.assertEqual(code, 0)
            self.assertIn("did the thing", human)
            import json
            self.assertEqual(json.loads(session.read_text()), {"a": 1, "b": 2})

    def test_failure_leaves_session_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            session = tmp / "session.json"
            session.write_text('{"a": 1}\n', encoding="utf-8")
            bindir = tmp / "bin"
            bindir.mkdir()
            self._make_fake_bin(bindir, "cgafail", (
                "import sys\n"
                "sys.stderr.write('boom\\n')\n"
                "sys.exit(3)\n"
            ))
            env = {"CGA_SESSION": str(session),
                   "PATH": str(bindir) + os.pathsep + os.environ["PATH"]}
            with mock.patch.dict(os.environ, env, clear=False):
                ok, code, human = cmd.run_argv(["cgafail"])
            self.assertFalse(ok)
            self.assertEqual(code, 3)
            self.assertIn("boom", human)
            self.assertEqual(session.read_text(), '{"a": 1}\n')

    def test_initialized_workflow_routes_through_dispatcher(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            (tmp / ".cga").mkdir()
            (tmp / ".cga" / "config").write_text("{}\n", encoding="utf-8")
            completed = mock.Mock(returncode=0, stdout=b"", stderr=b"recorded\n")
            env = {"CGA_WORKFLOW_ROOT": str(tmp)}
            with mock.patch.dict(os.environ, env, clear=False), \
                    mock.patch.object(cmd, "_is_allowed", return_value=True), \
                    mock.patch.object(cmd.cgast, "cga_root",
                                      return_value=CGA_ROOT), \
                    mock.patch.object(cmd.subprocess, "run",
                                      return_value=completed) as run:
                ok, code, human = cmd.run_argv(["cgasi", "view", "--erc", "40"])
            self.assertTrue(ok)
            self.assertEqual(code, 0)
            self.assertEqual(human, "recorded\n")
            invoked = run.call_args.args[0]
            self.assertEqual(
                invoked,
                [str(CGA_ROOT / "cga"), "-C", str(tmp), "si",
                 "view", "--erc", "40"],
            )
            self.assertEqual(
                run.call_args.kwargs["env"]["CGA_SOURCE_STEP"], "dashboard")


if __name__ == "__main__":
    unittest.main()
