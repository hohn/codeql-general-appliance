import json
import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "lib"))

from cgactl.db import Database  # noqa: E402


class DatabaseTest(unittest.TestCase):
    @mock.patch("cgactl.db.subprocess.run")
    def test_large_values_are_streamed_in_sql_not_argv(self, run):
        run.return_value = mock.Mock(returncode=0, stdout='{"ok":true}\n',
                                     stderr="")
        payload = {"jobs": [{"value": "x" * 200000}]}
        result = Database(psql="psql").json(
            "SELECT consume(:'doc'::jsonb);", {"doc": payload})
        argv = run.call_args.args[0]
        sent_sql = run.call_args.kwargs["input"]
        self.assertEqual(result, {"ok": True})
        self.assertLess(sum(len(x) for x in argv), 1000)
        self.assertIn(json.dumps(payload, separators=(",", ":")), sent_sql)
        self.assertNotIn(":'doc'", sent_sql)

    @mock.patch("cgactl.db.subprocess.run")
    def test_parameter_text_cannot_replace_another_placeholder(self, run):
        run.return_value = mock.Mock(returncode=0, stdout="ok\n", stderr="")
        Database(psql="psql").run(
            "SELECT :'first', :'second';",
            {"first": "text :'second' text", "second": "safe"})
        sent_sql = run.call_args.kwargs["input"]
        self.assertIn("text :'second' text", sent_sql)
        self.assertEqual(sent_sql.count("safe"), 1)


if __name__ == "__main__":
    unittest.main()
