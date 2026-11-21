import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "mrvacommander/.env.container"
UPLOADS = ("populate-dbstore.sh", "populate-qpstore.sh")


class ContainerCredentialsTest(unittest.TestCase):
    def environment(self):
        return {
            key: value for key, value in os.environ.items()
            if not key.startswith(("MINIO_ROOT_", "ARTIFACT_MINIO_", "QLDB_MINIO_"))
        }

    def read_config(self, env):
        inspect = (
            "import json,os; print(json.dumps({k:v for k,v in os.environ.items() "
            'if k.startswith(("MINIO_ROOT_", "ARTIFACT_MINIO_", "QLDB_MINIO_"))}))'
        )
        return subprocess.run(
            ["/bin/bash", "-c",
             'set -a; source "$1"; shift; exec "$@"',
             "credentials", str(CONFIG), sys.executable, "-c", inspect],
            env=env, capture_output=True, text=True,
        )

    def test_template_rejects_missing_and_empty_password(self):
        for password in (None, ""):
            with self.subTest(password=password):
                env = self.environment()
                if password is not None:
                    env["MINIO_ROOT_PASSWORD"] = password
                result = self.read_config(env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("MINIO_ROOT_PASSWORD", result.stderr)

    def test_template_preserves_operator_credentials_and_store_overrides(self):
        env = self.environment()
        env.update(
            MINIO_ROOT_USER="operator",
            MINIO_ROOT_PASSWORD=secrets.token_urlsafe(24),
            ARTIFACT_MINIO_SECRET=secrets.token_urlsafe(24),
            ARTIFACT_MINIO_ENDPOINT="artifacts.example.test:9000",
            QLDB_MINIO_ID="database-operator",
        )
        result = self.read_config(env)
        self.assertEqual(result.returncode, 0, result.stderr)
        configured = json.loads(result.stdout)
        for key in ("MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD",
                    "ARTIFACT_MINIO_SECRET", "ARTIFACT_MINIO_ENDPOINT", "QLDB_MINIO_ID"):
            self.assertEqual(configured[key], env[key])
        self.assertEqual(configured["ARTIFACT_MINIO_ID"], env["MINIO_ROOT_USER"])
        self.assertEqual(configured["QLDB_MINIO_SECRET"], env["MINIO_ROOT_PASSWORD"])

    def run_upload(self, name, password):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            calls = directory / "calls.json"
            mc = directory / "mc"
            mc.write_text(
                "#!" + sys.executable + "\n"
                "import json,os,pathlib,sys\n"
                "p=pathlib.Path(os.environ['MC_CALLS'])\n"
                "calls=json.loads(p.read_text()) if p.exists() else []\n"
                "p.write_text(json.dumps(calls+[sys.argv[1:]]))\n"
            )
            mc.chmod(0o700)
            (directory / "dbstore-data").mkdir()
            env = self.environment()
            env.update(PATH=str(directory) + os.pathsep + os.defpath,
                       MC_CALLS=str(calls), MINIO_ROOT_USER="operator")
            if password is not None:
                env["MINIO_ROOT_PASSWORD"] = password
            result = subprocess.run(
                ["/bin/bash", str(ROOT / "mrvacommander" / name)],
                cwd=directory, env=env, capture_output=True, text=True,
            )
            return result, json.loads(calls.read_text()) if calls.exists() else []

    def test_uploads_reject_missing_and_empty_password_before_contacting_mc(self):
        for name in UPLOADS:
            for password in (None, ""):
                with self.subTest(script=name, password=password):
                    result, calls = self.run_upload(name, password)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("MINIO_ROOT_PASSWORD", result.stderr)
                    self.assertEqual(calls, [])

    def test_uploads_pass_supplied_credentials_without_shell_splitting(self):
        password = secrets.token_urlsafe(24) + " 'space $literal"
        for name in UPLOADS:
            with self.subTest(script=name):
                result, calls = self.run_upload(name, password)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls[0][:2], ["alias", "set"])
                self.assertEqual(calls[0][-2:], ["operator", password])


if __name__ == "__main__":
    unittest.main()
