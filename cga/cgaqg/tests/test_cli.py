from __future__ import annotations

import argparse
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
sys.path.insert(0, str(REPO_ROOT / "cga" / "cgaql"))
from cgaqg import cli  # noqa: E402
from cgaql import catalog  # noqa: E402


QUERY = """/**
 * @id cga/test-location
 * @name Test location
 * @description Reports a location for review.
 * @kind problem
 * @problem.severity recommendation
 */
import cpp
from File f
where f.getBaseName() = "x.c"
select f, "Review this location."
"""


class CgaqgTest(unittest.TestCase):
    def test_materialize_and_index_prepares_library_without_selecting(self):
        scratch = CGA_PREP_ROOT / "cga-prep-tmp"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as raw, mock.patch.dict(
                "os.environ", {"CGAST_ROOT": str(CGA_PREP_ROOT),
                               "CGAST_TMPDIR": raw}):
            work = Path(raw) / "work.json"
            cli.workflow.write_json(work, {"items": [
                {"queries": [{"id": "cga/test-location", "name": "Test",
                              "filename": "Test.ql", "source": QUERY}]},
                {"queries": [{"id": "cga/test-location", "name": "Test",
                              "filename": "Test.ql", "source": QUERY}]},
            ]})
            state = {"cgacv-work-items": cli.cgast.rel(work)}
            cli.cmd_materialize(state, argparse.Namespace(
                output_dir=str(Path(raw) / "queries")))
            cli.cmd_index(state, argparse.Namespace())
            conn = catalog.connect(cli.cgast.resolve(state[cli.INDEX_KEY]))
            try:
                self.assertEqual(catalog.count(conn), 1)
            finally:
                conn.close()
            self.assertEqual(
                cli.cgast.resolve(state[cli.QUERYDIR_KEY]),
                (Path(raw) / "queries").resolve(),
            )
            self.assertNotIn("cgaql-querydir", state)
            self.assertNotIn("cgaql-index", state)
            self.assertNotIn("cgaql-selection", state)

    def test_no_queries_fails_clearly(self):
        scratch = CGA_PREP_ROOT / "cga-prep-tmp"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as raw, mock.patch.dict(
                "os.environ", {"CGAST_ROOT": str(CGA_PREP_ROOT),
                               "CGAST_TMPDIR": raw}):
            work = Path(raw) / "work.json"
            cli.workflow.write_json(work, {"items": [{"queries": []}]})
            with self.assertRaises(cli.workflow.WorkflowError):
                cli._query_defs({"cgacv-work-items": cli.cgast.rel(work)})

    def test_materialize_copies_sibling_qll_modules(self):
        scratch = CGA_PREP_ROOT / "cga-prep-tmp"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as raw, mock.patch.dict(
                "os.environ", {"CGAST_ROOT": str(CGA_PREP_ROOT),
                               "CGAST_TMPDIR": raw}):
            source_dir = Path(raw) / "source"
            source_dir.mkdir()
            query = source_dir / "Test.ql"
            query.write_text(QUERY, encoding="utf-8")
            support = source_dir / "Support.qll"
            support.write_text("predicate support() { any() }\n",
                               encoding="utf-8")
            work = Path(raw) / "work.json"
            cli.workflow.write_json(work, {"items": [
                {"queries": [{"id": "cga/test-location", "name": "Test",
                              "filename": "Test.ql",
                              "path": cli.cgast.rel(query)}]},
            ]})
            state = {"cgacv-work-items": cli.cgast.rel(work)}
            output = Path(raw) / "queries"
            cli.cmd_materialize(
                state, argparse.Namespace(output_dir=str(output)))
            self.assertEqual(
                (output / "Support.qll").read_text(encoding="utf-8"),
                support.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
