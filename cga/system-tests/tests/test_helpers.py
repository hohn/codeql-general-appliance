import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HelperArgumentsTest(unittest.TestCase):
    def test_system11_help_and_unknown_phases_do_not_create_runtime(self):
        for arguments, expected in (([], 0), (["--help"], 0),
                                    (["--unknown"], 2),
                                    (["reset", "--unknown"], 2)):
            with self.subTest(arguments=arguments), \
                    tempfile.TemporaryDirectory() as raw:
                work = Path(raw) / "experiment"
                result = subprocess.run(
                    [str(ROOT / "run-system-11/run"), *arguments],
                    env={**os.environ, "CGA_SYSTEM11_ROOT": str(work)},
                    capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertFalse(work.exists())

    def test_help_and_unknown_arguments_do_not_touch_runtime(self):
        for helper in ("cleanup", "query"):
            for argument, expected in (("--help", 0), ("--unknown", 2), ("", 2)):
                with self.subTest(helper=helper, argument=argument), \
                     tempfile.TemporaryDirectory() as raw:
                    root = Path(raw)
                    work = root / "work"
                    work.mkdir()
                    marker = work / "preserved"
                    marker.write_text("keep")
                    runtime = root / "runtime"
                    result = subprocess.run(
                        [str(ROOT / f"{helper}-standalone-multi-agent-e2e.sh"),
                         argument],
                        env={
                            **os.environ,
                            "PORT": "0",
                            "DB_SERVER_PORT": "0",
                            "POSTGRES_HOST": "127.0.0.1",
                            "POSTGRES_PORT": "1",
                            "PGCONNECT_TIMEOUT": "1",
                            "MRVA_STANDALONE_STORAGE": "filesystem",
                            "MRVA_WORK_DIR": str(work),
                            "MRVA_TMP_DIR": str(runtime),
                            "SERVER_PID": "",
                            "SERVER_PID_FILE": str(runtime / "server.pid"),
                            "DB_SERVER_PID_FILE": str(runtime / "db-server.pid"),
                            "STATE_FILE": str(runtime / "state"),
                        },
                        capture_output=True, text=True, timeout=10,
                    )
                    self.assertEqual(result.returncode, expected, result.stderr)
                    self.assertEqual(marker.read_text(), "keep")
                    self.assertFalse(runtime.exists())


if __name__ == "__main__":
    unittest.main()
