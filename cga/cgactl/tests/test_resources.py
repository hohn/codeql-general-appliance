import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "lib"))

from cgactl.resources import measure  # noqa: E402


class ResourceTest(unittest.TestCase):
    def test_measure_writes_raw_summary_and_report(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            code, summary = measure(
                ["sh", "-c", "printf hello; sleep .25"], root, .2,
                root / "command.log")
            self.assertEqual(code, 0)
            self.assertEqual((root / "command.log").read_text(), "hello")
            self.assertGreaterEqual(summary["samples"], 1)
            samples = [json.loads(line) for line in
                       (root / "resource_samples.jsonl").read_text().splitlines()]
            self.assertEqual(len(samples), summary["samples"])
            self.assertTrue((root / "resource_summary.json").is_file())
            self.assertIn("resource_samples.jsonl",
                          (root / "resource_report.html").read_text())

    def test_measure_can_pass_stdout_through(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            code, summary = measure(
                ["sh", "-c", "printf state; printf diagnostic >&2"],
                root, .2, root / "command.log",
                passthrough_stdout=True)
            self.assertEqual(code, 0)
            self.assertEqual((root / "command.log").read_text(), "diagnostic")
            self.assertEqual(summary["exit_code"], 0)


if __name__ == "__main__":
    unittest.main()
