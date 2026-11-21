from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
CGA_ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(CGA_ROOT / "cgalib"))
sys.path.insert(0, str(CGA_ROOT / "cgasi"))

from cgaex import cli, export, serve  # noqa: E402


FINDINGS = [{
    "user": "bob",
    "file_name": "job-01-acme-bob.sarif",
    "kind": "problem",
    "rule_id": "cpp/cve-location",
    "rule_name": "CVE location",
    "uri": "crc32.c",
    "start_line": 42,
    "start_column": 3,
}]

STATE = {"cgasi-ingestions": {
    "run-1": {
        "name": "run-1", "user": "bob", "session_id": 7,
        "language": "cpp", "status": "succeeded", "query_pack": "one.tgz",
        "finding_count": 1,
        "jobs": [{
            "repository": "acme/bob", "status": "succeeded",
            "finding_count": 1, "mrva_result_count": 1,
            "artifact_size_bytes": 100,
            "artifacts": {
                "archive": "run-1/acme-bob.zip",
                "sarif": "run-1/job-01-acme-bob.sarif",
                "sqlite": "run-1/job-01-acme-bob.sqlite",
            },
        }],
    },
    "run-2": {
        "name": "run-2", "user": "eve", "session_id": 8,
        "language": "cpp", "status": "succeeded", "query_pack": "two.tgz",
        "finding_count": 0,
        "jobs": [{
            "repository": "acme/eve", "status": "succeeded",
            "finding_count": 0, "mrva_result_count": 0,
            "artifact_size_bytes": 50,
            "artifacts": {
                "archive": "run-2/acme-eve.zip",
                "sarif": "run-2/job-01-acme-eve.sarif",
                "sqlite": "run-2/job-01-acme-eve.sqlite",
            },
        }],
    },
}}


class ExportTest(unittest.TestCase):
    def test_legacy_parallel_artifact_shape_is_rejected(self) -> None:
        state = {"cgasi-ingestions": {"old": {
            "user": "bob", "archives": ["one.zip"],
            "sarifs": ["one.sarif"], "sqlites": ["one.sqlite"],
            "result_rows": 1,
        }}}
        with self.assertRaisesRegex(export.ExportError, "has no jobs"):
            export.llm_document(state, FINDINGS)

    def test_renderers_preserve_summary_and_findings(self) -> None:
        human = export.render_human(STATE, FINDINGS)
        machine = json.loads(export.render_llm(STATE, FINDINGS))
        self.assertIn("crc32.c:42", human)
        self.assertIn("acme/eve", human)
        self.assertEqual(machine["schema"], "cga.analysis-export.v2")
        self.assertEqual(machine["summary"]["finding_count"], 1)
        self.assertEqual(machine["summary"]["submission_count"], 2)
        self.assertEqual(machine["summary"]["job_count"], 2)
        self.assertEqual(machine["summary"]["zero_finding_job_count"], 1)
        self.assertEqual(machine["summary"]["users"], ["bob", "eve"])
        self.assertEqual(machine["summary"]["findings_by_user"],
                         {"bob": 1, "eve": 0})
        self.assertEqual(machine["summary"]["jobs_by_status"],
                         {"succeeded": 2})
        self.assertEqual(machine["submissions"][1]["finding_count"], 0)
        self.assertEqual(machine["submissions"][1]["jobs"][0]
                         ["repository"], "acme/eve")
        self.assertEqual(machine["findings"][0]["submission"], "run-1")
        self.assertEqual(machine["findings"][0]["session_id"], 7)
        self.assertEqual(machine["findings"][0]["job_index"], 1)
        self.assertEqual(machine["findings"][0]["repository"], "acme/bob")

    def test_commands_record_both_formats(self) -> None:
        state = {"cgasi-db": "results.duckdb", **STATE}
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with mock.patch.object(cli, "_findings", return_value=FINDINGS):
                cli.cmd_human(
                    state, argparse.Namespace(output=str(root / "report.md")))
                cli.cmd_llm(
                    state, argparse.Namespace(output=str(root / "report.json")))
            self.assertEqual(set(state[cli.EXPORTS_KEY]), {"human", "llm"})
            self.assertIn("crc32.c", (root / "report.md").read_text())
            document = json.loads((root / "report.json").read_text())
            self.assertEqual(document["findings"][0]["repository"],
                             "acme/bob")

    def test_fragments_show_exports(self) -> None:
        state = {
            "cgaex-exports": {
                "human": {"path": "report.md", "finding_count": 1}
            },
            "cgaex-active": "human",
            "cgaex-finding-count": 1,
        }
        with mock.patch.object(serve.cgast, "load_session",
                               return_value=state):
            self.assertIn("human", serve.overview_fragment())
            self.assertIn("report.md", serve.detail_fragment())


if __name__ == "__main__":
    unittest.main()
