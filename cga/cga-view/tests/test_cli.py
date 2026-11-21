from __future__ import annotations

import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
CGA_ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT))

from cgaview import cli  # noqa: E402


class CaptureTest(unittest.TestCase):
    def test_capture_fetches_every_dashboard_fragment(self) -> None:
        with mock.patch.object(
            cli,
            "_fetch_fragment",
            side_effect=lambda url, _timeout: f"<p>{url}</p>",
        ):
            snapshot = cli.capture_snapshot("cgamr status --name bob-1", 1)

        self.assertEqual(snapshot["label"], "cgamr status --name bob-1")
        self.assertEqual(
            set(snapshot["fragments"]),
            {
                "cgasv/header",
                "cgadl/overview",
                "cgadl/detail",
                "cgaql/overview",
                "cgaql/detail",
                "cgamr/overview",
                "cgamr/detail",
                "cgamu/overview",
                "cgamu/detail",
                "cgasi/overview",
                "cgasi/detail",
                "cgaex/overview",
                "cgaex/detail",
            },
        )

    def test_capture_is_all_or_nothing(self) -> None:
        def fetch(url: str, _timeout: float) -> str:
            if url.endswith("/detail"):
                raise urllib.error.URLError("offline")
            return "<p>ok</p>"

        with mock.patch.object(cli, "_fetch_fragment", side_effect=fetch):
            with self.assertRaisesRegex(
                RuntimeError, "dashboard capture failed"
            ):
                cli.capture_snapshot("broken capture", 1)

    def test_dump_reader_skips_partial_lines(self) -> None:
        snapshot = {"fragments": {"cgasv/header": "<p>ok</p>"}}
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / "capture.jsonl"
            dump.write_text(
                "\n" + json.dumps(snapshot) + "\n{\"fragments\":",
                encoding="utf-8",
            )
            self.assertEqual(cli.read_snapshots(dump), [snapshot])

    def test_append_preserves_capture_after_truncated_tail(self) -> None:
        snapshot = {"fragments": {"cgasv/header": "<p>next</p>"}}
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / "capture.jsonl"
            dump.write_text('{"fragments":', encoding="utf-8")
            cli.append_snapshot(dump, snapshot)
            self.assertEqual(cli.read_snapshots(dump), [snapshot])


class ExportTest(unittest.TestCase):
    def test_export_is_self_contained_and_script_safe(self) -> None:
        snapshots = [
            {
                "captured_at": "2026-07-29T13:00:00-07:00",
                "label": "capture </script><img src=x>",
                "fragments": {
                    "cgasv/header": "<div>header</div>",
                    "cgadl/overview": "<div>dbs</div>",
                },
            }
        ]
        page = cli.build_export(snapshots, CGA_ROOT)

        self.assertIn("--cga-bg:", page)
        self.assertIn(':root[data-theme="light"]', page)
        self.assertIn('id="cga-theme-toggle"', page)
        self.assertIn("localStorage.getItem(THEME_STORAGE_KEY)", page)
        self.assertIn("window.CGA_DASHBOARD_SNAPSHOTS", page)
        self.assertIn('id="cga-progress"', page)
        self.assertIn(r"\u003c/script>", page)
        self.assertNotIn('<link rel="stylesheet"', page)
        self.assertNotIn('src="cga.js"', page)
        self.assertNotIn('src="cga.js?', page)
        self.assertNotIn('src="cga-config.js"', page)


if __name__ == "__main__":
    unittest.main()
