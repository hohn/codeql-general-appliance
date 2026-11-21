import http.cookiejar
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import urlencode
from urllib.request import build_opener, HTTPCookieProcessor, Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cgalib"))
from cgacc import cli
from cgacc.runtime import EditorError, Editors, executable, validate_port


class RuntimeTest(unittest.TestCase):
    def test_serve_help_is_public_and_does_not_start_editor(self):
        output = io.StringIO()
        with mock.patch.object(sys, "argv", ["cgacc", "serve", "--help"]), \
                mock.patch.object(cli, "Editors") as manager, \
                contextlib.redirect_stdout(output), \
                self.assertRaises(SystemExit) as stopped:
            cli.main()
        self.assertEqual(stopped.exception.code, 0)
        manager.assert_not_called()
        help_text = output.getvalue()
        self.assertIn("cga cc serve - ", help_text)
        self.assertIn("CGACC_CODE_SERVER", help_text)
        self.assertIn("generated login password", help_text)
        self.assertIn("Example", help_text)

    def test_port_validation_and_occupied_port_never_fall_back(self):
        for port in (-1, 65536, True, "8611"):
            with self.subTest(port=port), self.assertRaisesRegex(EditorError, "editor port"):
                validate_port(port)
        with tempfile.TemporaryDirectory() as temporary, socket.socket() as listener:
            directory = Path(temporary)
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            editors = Editors()
            self.addCleanup(editors.close)
            with mock.patch("cgacc.runtime.executable", return_value="/bin/false"), \
                    mock.patch("cgacc.runtime.subprocess.Popen") as launch:
                with self.assertRaisesRegex(EditorError, "cannot bind editor port"):
                    editors.open("one", directory, directory / "query.code-workspace",
                                 directory / "runtime", port=listener.getsockname()[1])
                launch.assert_not_called()

    def test_cli_forwards_selected_port(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "query.code-workspace"
            project.write_text('{"folders":[{"path":"."}]}')
            with mock.patch.object(sys, "argv", [
                    "cgacc", "serve", str(project), "--runtime", temporary, "--port", "8611"]), \
                    mock.patch.object(cli, "Editors") as manager, \
                    mock.patch.object(cli.signal, "signal"), \
                    mock.patch.object(cli.time, "sleep", side_effect=KeyboardInterrupt), \
                    mock.patch("builtins.print"):
                manager.return_value.open.return_value = {}
                self.assertEqual(cli.main(), 0)
                self.assertEqual(manager.return_value.open.call_args.kwargs, {"port": 8611})
                manager.return_value.close.assert_called_once()

    def test_missing_and_failed_executable_are_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            project = directory / "query.code-workspace"
            project.write_text('{"folders":[{"path":"."}]}')
            editors = Editors()
            self.addCleanup(editors.close)
            with mock.patch.dict(os.environ, {"CGACC_CODE_SERVER": "/does/not/exist"}):
                with self.assertRaisesRegex(EditorError, "not executable"):
                    editors.open("one", directory, project, directory / "runtime")
            with mock.patch.dict(os.environ, {"CGACC_CODE_SERVER": "/bin/false"}):
                with self.assertRaisesRegex(EditorError, "code-server exited"):
                    editors.open("one", directory, project, directory / "runtime")
            self.assertEqual(editors.values, {})

    def test_native_auth_reuse_isolation_restart_and_shutdown(self):
        try:
            executable()
        except EditorError as exc:
            self.skipTest(str(exc))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                fixed_port = listener.getsockname()[1]
            editors = Editors()
            self.addCleanup(editors.close)
            def launch(key):
                directory = root / key
                directory.mkdir(exist_ok=True)
                project = directory / "query.code-workspace"
                project.write_text(json.dumps({"folders": [{"path": "."}]}))
                return editors.open(key, directory, project, root / "runtime" / key,
                                    port=fixed_port if key == "one" else 0)
            try:
                first = launch("one")
                self.assertTrue(first["url"].startswith(f"http://127.0.0.1:{fixed_port}/"))
                self.assertEqual(first["pid"], launch("one")["pid"])
                with urlopen(first["url"], timeout=10) as response:
                    self.assertIn("/login", response.url)
                cookies = http.cookiejar.CookieJar()
                browser = build_opener(HTTPCookieProcessor(cookies))
                with browser.open(Request(
                        first["login"], data=urlencode({"password": first["password"]}).encode()),
                        timeout=10) as response:
                    self.assertNotIn("/login", response.url)
                    self.assertIn("workspace=", response.url)
                    self.assertIn(b"code-server", response.read())
                self.assertTrue(list(cookies))
                self.assertNotIn(first["password"], first["url"])
                self.assertEqual(Path(f"/proc/{first['pid']}/cwd").resolve(), root / "one")
                self.assertNotIn(first["password"],
                                 (root / "runtime/one/code-server.log").read_text())
                second = launch("two")
                self.assertNotEqual(first["pid"], second["pid"])
                self.assertNotEqual(first["url"], second["url"])
                exited = editors.values["one"]
                exited.close()
                restarted = launch("one")
                self.assertNotEqual(first["pid"], restarted["pid"])
                self.assertEqual(first["url"], restarted["url"])
                owned = list(editors.values.values())
                editors.close()
                self.assertTrue(all(value.process.poll() is not None for value in owned))
                with self.assertRaisesRegex(EditorError, "stopping"):
                    launch("three")
            finally:
                editors.close()


if __name__ == "__main__":
    unittest.main()
