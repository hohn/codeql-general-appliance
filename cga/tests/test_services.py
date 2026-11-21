"""Service boundaries, CGAST preservation, and isolated lifecycle regression tests."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "lib"), str(ROOT.parent / "cga/cgalib"),
                str(ROOT.parent / "cga/cgamx")]
for name in ("cgapg", "cgadbserve", "cgamrva"):
    sys.path.insert(0, str(ROOT / name))
import service
from cgapg import cli as pg
from cgadbserve import cli as dbserve
from cgamrva import cli as mrva


class Services(unittest.TestCase):
    def test_cli_invalid_state_emits_no_json(self):
        for name in ("cgapg", "cgadbserve", "cgamrva"):
            result = subprocess.run([ROOT / name / "bin" / name, "stop"],
                                    input='[]', capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')

    def test_info_preserves_foreign_keys(self):
        for name in ("cgapg", "cgadbserve", "cgamrva"):
            state = {"foreign": {"keep": 1}, name: {"status": "stopped",
                     "bin_dir": "/not-used", "data_dir": "/not-used"}}
            result = subprocess.run([ROOT / name / "bin" / name, "info"],
                                    input=json.dumps(state), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), state)

    def test_stop_does_not_signal_reused_pid(self):
        rt = {"pid": os.getpid(), "identity": ["wrong-boot", "wrong-start"]}
        with patch.object(service.os, "killpg") as kill:
            service.stop(rt)
        kill.assert_not_called()
        self.assertEqual(rt["status"], "stopped")

    def test_pg_init_preserves_keys_and_refuses_existing_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(cmd="init", data_dir=Path(tmp) / "pg",
                                      bin_dir=Path("/tools"), port=55439, user="study")
            state = {"foreign": 42}
            with patch.object(service, "command") as command, patch.object(service, "free_port"):
                pg.execute(state, args)
            self.assertEqual(state["foreign"], 42)
            self.assertEqual(state["cgapg"]["status"], "initialized")
            self.assertIn("initdb", str(command.call_args))
            args.data_dir.mkdir()
            with self.assertRaises(ValueError), patch.object(service, "command") as command:
                pg.execute({}, args)
            command.assert_not_called()

    def test_createdb_uses_recorded_connection_not_environment(self):
        rt = {"bin_dir": "/tools", "data_dir": "/data", "port": 12345, "user": "study"}
        with patch.object(service, "owned", return_value=True), patch.object(service, "command") as command:
            pg.execute({"cgapg": rt}, argparse.Namespace(cmd="createdb", name="my-db"))
        argv = command.call_args.args[0]
        self.assertEqual(argv[-2:], ["--", "my-db"])
        self.assertIn("12345", argv)

    def test_pg_start_does_not_touch_existing_postmaster(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "postmaster.pid").write_text("123\n")
            state = {"cgapg": {"data_dir": tmp, "bin_dir": "/tools",
                                "status": "initialized"}}
            with patch.object(service, "command") as command, self.assertRaises(ValueError):
                pg.execute(state, argparse.Namespace(cmd="start"))
            command.assert_not_called()

    def test_mrva_start_does_not_start_dependencies(self):
        with patch.dict(os.environ, {"PORT": "18081", "SERVER_LOG": "/log",
                "MRVA_QLDB_DIR": "/db", "MRVA_WORK_DIR": "/work",
                "MRVA_DB_SERVER_URL": "http://127.0.0.1:19080",
                "MRVA_DBG_DUMP_SYSVIEW": ""}), \
                patch.object(mrva.infra, "config"), \
                patch.object(mrva.infra, "server_start") as combined, \
                patch.object(service, "start") as start:
            mrva.execute({}, argparse.Namespace(cmd="start", binary=Path("/mrvaserver")))
        combined.assert_not_called()
        self.assertEqual(start.call_args.args[1], "cgamrva")
        self.assertEqual(start.call_args.args[2][0], Path("/mrvaserver"))

    def test_mrva_check_rejects_errors_but_allows_known_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "log"
            state = {"cgamrva": {"log": str(log)}}
            log.write_text("ERROR mrva-project-resolver missing\n")
            with patch.object(service, "check"):
                mrva.execute(state, argparse.Namespace(cmd="check"))
                log.write_text("ERROR unexpected\n")
                with self.assertRaises(ValueError):
                    mrva.execute(state, argparse.Namespace(cmd="check"))

    def test_dbserve_real_lifecycle_preserves_state_and_files(self):
        with tempfile.TemporaryDirectory() as tmp, socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            sock.close()
            state = {"foreign": 42}
            args = argparse.Namespace(cmd="start", directory=Path(tmp) / "archives",
                                      port=port, log=Path(tmp) / "http.log")
            dbserve.execute(state, args)
            try:
                dbserve.execute(state, argparse.Namespace(cmd="check"))
                with self.assertRaises(ValueError):
                    dbserve.execute(state, args)
            finally:
                dbserve.execute(state, argparse.Namespace(cmd="stop"))
            self.assertEqual(state["foreign"], 42)
            self.assertTrue(args.log.exists())
            service.free_port(port)

    def test_occupied_port_is_not_reclaimed(self):
        with socket.socket() as sock, tempfile.TemporaryDirectory() as tmp:
            sock.bind(("127.0.0.1", 0))
            sock.listen()
            with self.assertRaises(OSError):
                service.start({}, "test", [sys.executable, "-c", "pass"],
                              sock.getsockname()[1], Path(tmp) / "log")
            self.assertFalse((Path(tmp) / "log").exists())

    def test_failed_start_has_no_success_state(self):
        with tempfile.TemporaryDirectory() as tmp, socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            sock.close()
            state = {"foreign": 42}
            with self.assertRaises(RuntimeError):
                service.start(state, "test", [sys.executable, "-c", "raise SystemExit(2)"],
                              port, Path(tmp) / "log")
            self.assertEqual(state, {"foreign": 42})


if __name__ == "__main__":
    unittest.main()
