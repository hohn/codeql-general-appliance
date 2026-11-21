from __future__ import annotations

import argparse
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
CGA_ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(CGA_ROOT / "cgalib"))

from cgaql import cli, serve  # noqa: E402


class HistoryTest(unittest.TestCase):
    def test_pack_explicit_output_reports_write_failure(self):
        with tempfile.TemporaryDirectory() as raw, mock.patch.dict(
                "os.environ", {"CGA_ROOT": raw, "CGA_TMPDIR": raw}):
            state = {}
            cli._write_selection(state, [
                {"id": "one", "language": "cpp", "path": "/queries/One.ql"}])
            parent = Path(raw) / "not-a-directory"
            parent.write_text("file")
            args = argparse.Namespace(dry_run=False, output=str(parent / "one.tgz"))
            with mock.patch.object(cli.pack, "build_query_pack",
                                   return_value=b"pack"), \
                 mock.patch.object(cli.cgast, "info") as info:
                with self.assertRaises(SystemExit) as error:
                    cli.cmd_pack(state, args)
            self.assertEqual(error.exception.code, 1)
            self.assertEqual(state[cli.PACK_KEY], [])
            self.assertTrue(any("ERROR" in call.args[0]
                                for call in info.call_args_list))

    def test_pack_explicit_output_requires_single_selection(self):
        with tempfile.TemporaryDirectory() as raw, mock.patch.dict(
                "os.environ", {"CGA_ROOT": raw, "CGA_TMPDIR": raw}):
            query = {"id": "one", "language": "cpp", "path": "/queries/One.ql"}
            state = {}
            cli._write_selection(state, [query])
            output = Path(raw) / "bundles" / "one.tgz"
            args = argparse.Namespace(dry_run=False, output=str(output))
            with mock.patch.object(cli.pack, "build_query_pack",
                                   return_value=b"pack") as build:
                cli.cmd_pack(state, args)
                self.assertEqual(output.read_bytes(), b"pack")
                self.assertEqual(cli.cgast.resolve(state[cli.PACK_KEY][0]), output)
                cli._write_selection(state, [query, query])
                with self.assertRaises(SystemExit):
                    cli.cmd_pack(state, args)
                self.assertEqual(build.call_count, 1)

    def test_user_selections_and_packs_accumulate(self):
        with tempfile.TemporaryDirectory() as raw_tmp, \
             mock.patch.dict("os.environ", {
                 "CGA_ROOT": raw_tmp,
                 "CGA_TMPDIR": str(Path(raw_tmp) / "tmp"),
             }):
            state = {}
            bob = {"id": "bob/query", "language": "cpp",
                   "kind": "problem", "severity": "warning",
                   "relpath": "Bob.ql", "path": "/queries/Bob.ql"}
            eve = {"id": "eve/query", "language": "cpp",
                   "kind": "problem", "severity": "warning",
                   "relpath": "Eve.ql", "path": "/queries/Eve.ql"}

            cli._write_selection(state, [bob], "bob")
            cli._write_selection(state, [eve], "eve")
            with mock.patch.object(cli.pack, "build_query_pack",
                                   return_value=b"pack"):
                cli.cmd_pack(state, argparse.Namespace(dry_run=False))

            history = state[cli.HISTORY_KEY]
            self.assertEqual([item["user"] for item in history],
                             ["bob", "eve"])
            self.assertNotIn("packs", history[0])
            self.assertEqual(len(history[1]["packs"]), 1)
            with mock.patch.object(serve.cgast, "load_session",
                                   return_value=state):
                detail = serve.detail_fragment()
            self.assertLess(detail.index("<th>user</th>"),
                            detail.index("<th>language</th>"))
            self.assertIn("bob/query", detail)
            self.assertIn("eve/query", detail)
            pack_path = cli.cgast.resolve(history[1]["packs"][0])
            self.assertTrue(pack_path.exists())
            cli.cmd_clean(state, argparse.Namespace())
            self.assertFalse(pack_path.exists())
            self.assertNotIn("packs", history[1])


if __name__ == "__main__":
    unittest.main()
