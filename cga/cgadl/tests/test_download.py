from __future__ import annotations

from contextlib import redirect_stderr
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
from pathlib import Path
import sys
import tempfile
import threading
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from cgadl import download  # noqa: E402


class DownloadTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.payload = b"database-" * 250000
        self.cut = 1024 * 1024
        self.mode = "normal"
        self.requests = []
        test = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requested = self.headers.get("Range")
                test.requests.append(requested)
                offset = int(requested.removeprefix("bytes=").removesuffix("-")) \
                    if requested else 0
                if requested and offset >= len(test.payload):
                    self.send_response(416)
                    self.end_headers()
                    return
                if test.mode == "bad-range":
                    self.send_response(206)
                    self.send_header("Content-Range",
                                     f"bytes 0-{len(test.payload)-1}/{len(test.payload)}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if requested and test.mode != "ignore-range":
                    self.send_response(206)
                    self.send_header(
                        "Content-Range",
                        f"bytes {offset}-{len(test.payload)-1}/{len(test.payload)}")
                    body = test.payload[offset:]
                else:
                    self.send_response(200)
                    body = test.payload
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if test.mode == "interrupt":
                    self.wfile.write(body[:test.cut])
                    test.mode = "normal"
                else:
                    self.wfile.write(body)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.row = {
            "git_owner": "owner", "git_repo": "repo",
            "result_url": f"http://127.0.0.1:{self.server.server_port}/database.zip",
            "content_hash": hashlib.sha256(self.payload).hexdigest(),
        }
        self.dest = download.db_dest(self.root, "owner", "repo")
        self.partial = self.dest.with_name(self.dest.name + ".part")

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def write_partial(self, content):
        self.partial.parent.mkdir(parents=True)
        self.partial.write_bytes(content)

    def test_interrupted_transfer_resumes_and_completed_archive_is_reused(self):
        self.mode = "interrupt"
        updates = []
        first = download.download([self.row], self.root,
                                  transfer_progress=lambda *args: updates.append(args))
        self.assertEqual(first[0].status, "error")
        self.assertFalse(self.dest.exists())
        self.assertEqual(self.partial.read_bytes(), self.payload[:self.cut])
        second = download.download([self.row], self.root,
                                   transfer_progress=lambda *args: updates.append(args))
        self.assertEqual(second[0].status, "downloaded")
        self.assertEqual(self.requests, [None, f"bytes={self.cut}-"])
        self.assertEqual(self.dest.read_bytes(), self.payload)
        self.assertFalse(self.partial.exists())
        self.assertIn(("owner", "repo", self.cut, len(self.payload)), updates)
        self.assertEqual(updates[-1], ("owner", "repo",
                                      len(self.payload), len(self.payload)))
        third = download.download([self.row], self.root)
        self.assertEqual(third[0].status, "skipped")
        self.assertEqual(len(self.requests), 2)

    def test_server_without_range_support_restarts_instead_of_appending(self):
        self.mode = "ignore-range"
        self.write_partial(self.payload[:self.cut])
        with redirect_stderr(io.StringIO()) as stderr:
            result = download.download([self.row], self.root)
        self.assertEqual(result[0].status, "downloaded")
        self.assertEqual(self.dest.read_bytes(), self.payload)
        self.assertIn("server ignored Range", stderr.getvalue())

    def test_invalid_content_range_keeps_existing_partial(self):
        self.mode = "bad-range"
        prefix = self.payload[:self.cut]
        self.write_partial(prefix)
        result = download.download([self.row], self.root)
        self.assertEqual(result[0].status, "error")
        self.assertIn("invalid resume Content-Range", result[0].error)
        self.assertFalse(self.dest.exists())
        self.assertEqual(self.partial.read_bytes(), prefix)

    def test_range_rejection_promotes_complete_partial_or_restarts_stale_one(self):
        self.write_partial(self.payload)
        result = download.download([self.row], self.root)
        self.assertEqual(result[0].status, "downloaded")
        self.assertEqual(self.requests, [f"bytes={len(self.payload)}-"])
        self.assertEqual(self.dest.read_bytes(), self.payload)

        self.dest.unlink()
        self.partial.write_bytes(b"x" * len(self.payload))
        with redirect_stderr(io.StringIO()) as stderr:
            result = download.download([self.row], self.root)
        self.assertEqual(result[0].status, "downloaded")
        self.assertIn("resume rejected", stderr.getvalue())
        self.assertEqual(self.requests[-2:], [f"bytes={len(self.payload)}-", None])
        self.assertEqual(self.dest.read_bytes(), self.payload)

    def test_checksums_and_force_prevent_reusing_corrupt_or_partial_archives(self):
        self.row["content_hash"] = "0" * 64
        result = download.download([self.row], self.root)
        self.assertEqual(result[0].status, "error")
        self.assertIn("SHA-256 mismatch", result[0].error)
        self.assertFalse(self.dest.exists())
        self.assertTrue(self.partial.exists())

        self.row["content_hash"] = hashlib.sha256(self.payload).hexdigest()
        self.dest.write_bytes(b"corrupt")
        result = download.download([self.row], self.root)
        self.assertEqual(result[0].status, "error")
        self.assertIn("--force", result[0].error)
        with redirect_stderr(io.StringIO()):
            result = download.download([self.row], self.root, force=True)
        self.assertEqual(result[0].status, "downloaded")
        self.assertEqual(self.requests[-1], None)
        self.assertEqual(self.dest.read_bytes(), self.payload)

    def test_file_urls_and_hashless_legacy_transfers_still_work(self):
        source = self.root / "source.zip"
        source.write_bytes(self.payload)
        self.row["result_url"] = source.as_uri()
        self.write_partial(b"unusable prefix")
        result = download.download([self.row], self.root)
        self.assertEqual(result[0].status, "downloaded")
        self.assertEqual(self.dest.read_bytes(), self.payload)
        self.dest.unlink()
        del self.row["content_hash"]
        result = download.download([self.row], self.root)
        self.assertEqual(result[0].status, "downloaded")
        self.assertEqual(self.dest.read_bytes(), self.payload)


if __name__ == "__main__":
    unittest.main()
