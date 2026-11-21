from __future__ import annotations

from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from cgaview.static_server import NoCacheHandler, serve  # noqa: E402


class StaticServerTest(unittest.TestCase):
    def test_every_response_disables_caching(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "index.html").write_text("dashboard", encoding="utf-8")
            handler = partial(NoCacheHandler, directory=str(root))
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            base = f"http://127.0.0.1:{server.server_port}"

            with urllib.request.urlopen(base + "/") as response:
                self.assertEqual(response.read(), b"dashboard")
                self.assertEqual(
                    response.headers["Cache-Control"],
                    "no-store, no-cache, must-revalidate, max-age=0",
                )
                self.assertEqual(response.headers["Pragma"], "no-cache")
                self.assertEqual(response.headers["Expires"], "0")
            with self.assertRaises(urllib.error.HTTPError) as missing:
                urllib.request.urlopen(base + "/missing")
            self.assertEqual(missing.exception.headers["Cache-Control"],
                             "no-store, no-cache, must-revalidate, max-age=0")
            missing.exception.close()

    def test_serve_validates_port_and_directory(self) -> None:
        with self.assertRaisesRegex(ValueError, "port must be"):
            serve(0, Path("."))
        with self.assertRaisesRegex(ValueError, "directory not found"):
            serve(8600, Path("/path/that/does/not/exist"))

    def test_runtime_config_overrides_assets_without_modifying_them(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            assets = root / "assets"
            assets.mkdir()
            original = assets / "cga-config.js"
            original.write_text("original")
            config = root / "cga-config.js"
            config.write_text("runtime-local")
            handler = partial(NoCacheHandler, directory=str(assets), config=config)
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            url = f"http://127.0.0.1:{server.server_port}/cga-config.js?v=1"
            with urllib.request.urlopen(url) as response:
                self.assertEqual(response.read(), b"runtime-local")
                self.assertIn("no-store", response.headers["Cache-Control"])
            request = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(request) as response:
                self.assertEqual(response.headers["Content-Length"], "13")
                self.assertEqual(response.read(), b"")
            self.assertEqual(original.read_text(), "original")


if __name__ == "__main__":
    unittest.main()
