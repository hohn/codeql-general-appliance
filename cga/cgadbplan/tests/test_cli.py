from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT.parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(REPO_ROOT / "cga" / "cgalib"))
from cgadbplan import cli  # noqa: E402


class CgadbPlanTest(unittest.TestCase):
    def test_info_help_does_not_read_preparation_state(self):
        output = io.StringIO()
        with mock.patch.object(cli.cgast, "read") as read, \
                contextlib.redirect_stdout(output), \
                self.assertRaises(SystemExit) as stopped:
            cli.main(["info", "--help"])
        self.assertEqual(stopped.exception.code, 0)
        read.assert_not_called()
        self.assertIn("cga db plan info", output.getvalue())
        self.assertIn("Description:", output.getvalue())

    def test_expand_creates_one_job_per_source_and_mode(self):
        items = [{
            "id": "cve-1--vulnerable",
            "owner": "debian",
            "repo": "zlib-vulnerable",
            "language": "cpp",
            "variant": "vulnerable",
            "version": "1",
            "source_dir": "/tmp/source",
            "source_tree_sha256": "a" * 64,
            "status": "ready",
            "trace_dependencies": [["check", "deps"]],
            "build_command": "make",
        }]
        jobs = cli.expand(
            items, ["bm-none", "trace"], "arm64", "arm64")
        self.assertEqual(len(jobs), 2)
        self.assertEqual(
            [job["repo"] for job in jobs],
            ["zlib-vulnerable-none-arm64",
             "zlib-vulnerable-trace-arm64"])
        self.assertEqual(
            [job["mode"] for job in jobs], ["bm-none", "trace"])
        self.assertEqual(jobs[0]["dependency_argv"], [])
        self.assertEqual(jobs[1]["dependency_argv"], [["check", "deps"]])

    def test_expand_rejects_duplicate_modes(self):
        with self.assertRaisesRegex(
                cli.workflow.WorkflowError, "modes must be unique"):
            cli.expand([], ["trace", "trace"], None, None)


if __name__ == "__main__":
    unittest.main()
