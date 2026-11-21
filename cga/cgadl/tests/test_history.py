from __future__ import annotations

import argparse
from contextlib import redirect_stderr
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
CGA_ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(CGA_ROOT / "cgalib"))

from cgadl import cli, serve  # noqa: E402


class HistoryTest(unittest.TestCase):
    def test_download_reports_byte_progress_and_completed_file_counts(self):
        with tempfile.TemporaryDirectory() as raw, \
                mock.patch.dict("os.environ", {
                    "CGA_ROOT": raw, "CGA_TMPDIR": str(Path(raw) / "tmp")}):
            rows = [{"git_owner": "owner", "git_repo": repo}
                    for repo in ("first", "second")]
            state = {}
            cli._write_selection(state, rows, "user")

            def transfer(rows, dbdir, *, progress, transfer_progress, **_kwargs):
                results = []
                for row in rows:
                    transfer_progress(row["git_owner"], row["git_repo"], 5, 10)
                    result = cli.download.DownloadResult(
                        row["git_owner"], row["git_repo"], "", dbdir / "file.zip",
                        "downloaded", size=10)
                    results.append(result)
                    progress(result)
                return results

            with mock.patch.object(cli.download, "download", side_effect=transfer), \
                    redirect_stderr(io.StringIO()) as stderr:
                cli.cmd_download(state, argparse.Namespace(
                    output_dir=str(Path(raw) / "dbs"), force=False, dry_run=False))
            self.assertIn("[1/2] DOWNLOADING owner/first:", stderr.getvalue())
            self.assertIn("[2/2] DOWNLOADING owner/second:", stderr.getvalue())
            self.assertIn("(50%)", stderr.getvalue())
            self.assertIn("[2/2] DOWNLOADED", stderr.getvalue())
            self.assertIn("2 ready, 0 error(s)", stderr.getvalue())

    def test_user_selections_accumulate_and_download_updates_active_entry(self):
        with tempfile.TemporaryDirectory() as raw_tmp, \
             mock.patch.dict("os.environ", {
                 "CGA_ROOT": raw_tmp,
                 "CGA_TMPDIR": str(Path(raw_tmp) / "tmp"),
             }):
            state = {}
            bob = {"git_owner": "flex", "git_repo": "flex",
                   "primary_language": "cpp", "tool_version": "1",
                   "db_file_size": 10, "result_url": "https://bob"}
            eve = {"git_owner": "maplibre", "git_repo": "native",
                   "primary_language": "cpp", "tool_version": "1",
                   "db_file_size": 20, "result_url": "https://eve"}

            cli._write_selection(state, [bob], "bob")
            cli._write_selection(state, [eve], "eve")
            output = Path(raw_tmp) / "dbs"
            args = argparse.Namespace(output_dir=str(output), force=False,
                                      dry_run=True)
            with mock.patch.object(cli.download, "download", return_value=[]):
                cli.cmd_download(state, args)

            self.assertEqual([item["user"] for item in state[cli.HISTORY_KEY]],
                             ["bob", "eve"])
            self.assertNotIn("dbdir", state[cli.HISTORY_KEY][0])
            self.assertEqual(state[cli.HISTORY_KEY][1]["dbdir"], "dbs")
            with mock.patch.object(serve.cgast, "load_session",
                                   return_value=state):
                detail = serve.detail_fragment()
            self.assertLess(detail.index("<th>user</th>"),
                            detail.index("<th>owner</th>"))
            self.assertIn("bob", detail)
            self.assertIn("eve", detail)
            self.assertIn("flex", detail)
            self.assertIn("maplibre", detail)


if __name__ == "__main__":
    unittest.main()
