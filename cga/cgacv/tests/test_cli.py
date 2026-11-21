from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
CGA_PREP_ROOT = PROJECT.parent
REPO_ROOT = CGA_PREP_ROOT.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(REPO_ROOT / "cga" / "cgalib"))
from cgacv import cli  # noqa: E402


class CgacvTest(unittest.TestCase):
    def test_validate_select_and_expand_three_variants(self):
        scratch = CGA_PREP_ROOT / "cga-prep-tmp"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as raw, mock.patch.dict(
                "os.environ", {"CGAST_ROOT": str(CGA_PREP_ROOT),
                               "CGAST_TMPDIR": raw}):
            spec = Path(raw) / "spec.json"
            query = Path(raw) / "Q.ql"
            query.write_text("import cpp\nselect 1\n", encoding="utf-8")
            doc = {
                "cves": [{
                    "id": "CVE-2020-1234", "url": "https://example.test/cve",
                    "debian": {"source_package": "pkg",
                               "tracker": "https://example.test/tracker"},
                    "language": "cpp",
                    "variants": [
                        {"name": name, "version": str(i),
                         "source": {"strategy": "git",
                                    "url": "https://example.test/repo.git",
                                    "ref": str(i)}}
                        for i, name in enumerate(
                            ["vulnerable", "patched", "most-recent"])
                    ],
                    "build": {"dependencies": [["make", "deps"]],
                              "command": "make"},
                    "queries": [{"id": "x/q", "name": "Q",
                                 "filename": "Q.ql", "path": "Q.ql"}],
                }]
            }
            spec.write_text(json.dumps(doc), encoding="utf-8")
            state = {}
            cli.cmd_import(state, argparse.Namespace(spec=str(spec)))
            cli.cmd_validate(state, argparse.Namespace(spec=None))
            cli.cmd_select(state, argparse.Namespace(cve="CVE-2020-1234"))
            cli.cmd_expand(state, argparse.Namespace())
            work = cli.workflow.load_json(
                cli.cgast.resolve(state[cli.WORK_KEY]))
            self.assertEqual(work["count"], 3)
            self.assertEqual({x["variant"] for x in work["items"]},
                             {"vulnerable", "patched", "most-recent"})
            self.assertTrue(all(len(x["queries"]) == 1 for x in work["items"]))

    def test_rejects_duplicate_or_missing_required_variants(self):
        base = {
            "id": "CVE-2020-1234", "url": "https://example.test/cve",
            "debian": {"source_package": "pkg",
                       "tracker": "https://example.test/tracker"},
            "language": "cpp",
            "variants": [
                {"name": "vulnerable", "version": "1",
                 "source": {"strategy": "git",
                            "url": "https://example.test/r", "ref": "1"}},
                {"name": "patched", "version": "2",
                 "source": {"strategy": "git",
                            "url": "https://example.test/r", "ref": "2"}},
                {"name": "patched", "version": "3",
                 "source": {"strategy": "git",
                            "url": "https://example.test/r", "ref": "3"}},
            ],
            "build": {"dependencies": [], "command": "make"}, "queries": [],
        }
        with self.assertRaises(cli.workflow.WorkflowError):
            cli.normalize_spec({"cves": [base]}, Path.cwd())


if __name__ == "__main__":
    unittest.main()
