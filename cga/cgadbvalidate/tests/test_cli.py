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
REPO_ROOT = CGA_ROOT.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(REPO_ROOT / "cga" / "cgalib"))
from cgadbvalidate import cli  # noqa: E402


class CgadbValidateTest(unittest.TestCase):
    def test_query_records_sarif_count(self):
        scratch = CGA_ROOT / "cga-prep-tmp"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as raw, mock.patch.dict(
                "os.environ", {"CGAST_ROOT": str(CGA_ROOT),
                               "CGAST_TMPDIR": raw}):
            root = Path(raw)
            database = root / "database"
            database.mkdir()
            records = root / "records.json"
            cli.workflow.write_json(records, {"items": [{
                "id": "record-1", "owner": "debian", "repo": "zlib",
                "status": "built", "database": str(database),
            }]})
            query = root / "query.ql"
            query.write_text("select 1\n")

            def run(argv, cwd=None):
                output = next(
                    part.split("=", 1)[1]
                    for part in argv if part.startswith("--output="))
                Path(output).write_text(json.dumps({
                    "runs": [{"results": [{}, {}]}],
                }))

            state = {cli.RECORDS_KEY: cli.cgast.rel(records)}
            with mock.patch.object(cli.workflow, "run", side_effect=run):
                cli.cmd_query(state, argparse.Namespace(
                    query=str(query), output_dir=str(root / "validation"),
                    record=[]))
            result = cli.workflow.load_json(
                cli.cgast.resolve(state[cli.RESULTS_KEY]))
            self.assertEqual(result["items"][0]["findings"], 2)


if __name__ == "__main__":
    unittest.main()
