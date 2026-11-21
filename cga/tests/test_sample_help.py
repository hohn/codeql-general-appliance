from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


COLLECTION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(COLLECTION / "cgalib"))

import help_view
import sample_help


class SampleHelpTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cga-sample-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = self.root / "sample workspace"
        self.environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith((
                "CGA_", "CGAST_", "MRVA_", "POSTGRES_", "MINIO_",
                "DB_SERVER_", "SERVER_",
            )) and key not in ("PORT", "RUN_TAG")
        }

    def cli(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            [COLLECTION / "cga", *args], cwd=self.root, env=self.environment,
            capture_output=True, text=True, check=check, timeout=30,
        )

    def step(self, number: str, check: bool = True, environment=None):
        step = next(step for step in sample_help.STEPS if step.number == number)
        return subprocess.run(
            ["bash", "-c", sample_help.script(step, self.workspace)],
            cwd=self.root, env=environment or self.environment,
            capture_output=True, text=True, check=check, timeout=60,
        )

    def state(self) -> dict:
        return json.loads(self.cli(
            "-C", str(self.workspace), "--json", "state", "show",
        ).stdout)

    def import_state(self, state: dict) -> None:
        source = self.root / "state.json"
        source.write_text(json.dumps(state), encoding="utf-8")
        self.cli("-C", str(self.workspace), "state", "import", str(source))

    def test_exact_aliases_and_help_never_execute(self) -> None:
        overview = self.cli("help", "sample", "05").stdout
        for args in (
            ("h", "s", "05"), ("help", "sample-05"), ("h", "sample-05", "-h"),
        ):
            self.assertEqual(self.cli(*args).stdout, overview)
        start = self.cli("help", "sample", "05", "00").stdout
        for args in (
            ("h", "s", "05", "start"),
            ("help", "sample-05", "00"),
            ("h", "s", "05", "00", "r", "-h"),
        ):
            self.assertEqual(self.cli(*args).stdout, start)
        for args in (
            ("h", "s", "05", "0"),
            ("h", "s", "05", "sta"),
            ("h", "s", "05", "00", "ru"),
            ("h", "s", "05", "00", "r", "extra"),
            ("h", "s", "05", "00", "r", "--unknown"),
            ("help", "--export", str(self.root / "bad.html"), "sample", "05"),
            ("h", "s", "06"),
        ):
            with self.subTest(arguments=args):
                result = self.cli(*args, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("error:", result.stderr)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_displayed_commands_are_the_exact_executable_shell(self) -> None:
        for step in sample_help.STEPS:
            with self.subTest(step=step.number):
                text = self.cli("h", "s", "05", step.number).stdout
                sections = help_view.split_sections(text)
                commands = next(s["text"] for s in sections if s["heading"] == "Commands")
                self.assertEqual(commands.rstrip(), sample_help.script(step).rstrip())
                subprocess.run(
                    ["bash", "-n"], input=commands, text=True,
                    capture_output=True, check=True,
                )
        with mock.patch.object(sample_help, "script", return_value="exit 7\n"):
            self.assertEqual(sample_help.run(sample_help.STEPS[0]), 7)
        for arguments in (
            ["sample", "05", "00", "run"],
            ["s", "05", "start", "r"],
            ["sample-05", "00", "r"],
        ):
            with mock.patch.object(sample_help, "run", return_value=7) as execute:
                self.assertEqual(help_view.main(arguments), 7)
                execute.assert_called_once_with(sample_help.STEPS[0])

    def test_completion_follows_sample_aliases(self) -> None:
        for words, index, expected in (
            ("h ''", 2, {"sample", "s", "sample-05", "getting-started"}),
            ("h s ''", 3, {"05"}),
            ("help sample 05 ''", 4, {"00", "start", "08", "13", "status", "20", "stop"}),
            ("h sample-05 ''", 3, {"00", "start", "08", "13", "status"}),
            ("h s 05 00 ''", 5, {"run", "r"}),
        ):
            result = subprocess.run(
                ["bash", "-c",
                 f'source "$1"; COMP_WORDS=("$2" {words}); COMP_CWORD={index}; '
                 '_cga; printf "%s\\n" "${COMPREPLY[@]}"',
                 "_", str(COLLECTION / "completions/cga.bash"), str(COLLECTION / "cga")],
                cwd=self.root, env=self.environment, check=True,
                capture_output=True, text=True,
            )
            self.assertTrue(expected <= set(result.stdout.splitlines()), result.stdout)

    def test_workspace_setup_and_library_steps_across_fresh_shells(self) -> None:
        initial = {
            **self.environment,
            "PORT": "18765",
            "MRVA_WORK_DIR": str(self.root / "runtime with 'quotes'"),
            "MRVA_POOL_MAX_WORKERS": "1",
        }
        self.step("00", environment=initial)
        settings = self.workspace / ".cga/sample-05.env"
        self.assertEqual(settings.stat().st_mode & 0o777, 0o600)
        before = settings.read_bytes()
        repeated = self.step("00", check=False)
        self.assertNotEqual(repeated.returncode, 0)
        self.assertEqual(settings.read_bytes(), before)
        restored = subprocess.run(
            ["bash", "-c", '. "$1"; printf "%s\\n" "$PORT" "$MRVA_WORK_DIR"',
             "_", str(settings)],
            env=self.environment, check=True, capture_output=True, text=True,
        )
        self.assertEqual(restored.stdout.splitlines(), [
            "18765", str(self.root / "runtime with 'quotes'"),
        ])
        for number in ("05", "06", "07", "08", "09"):
            self.step(number)
        state = self.state()
        selection = self.workspace / state["cgadl-selection"]
        rows = json.loads(selection.read_text())["databases"]
        self.assertEqual(
            [(row["git_owner"], row["git_repo"]) for row in rows],
            [("dsvpn", "dsvpn"), ("file", "file"), ("flex", "flex"),
             ("inotify-tools", "inotify-tools"), ("nnn", "nnn")],
        )
        blocked = self.step("14", check=False)
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("run step 13 before download", blocked.stderr)
        self.assertFalse((self.workspace / "downloads").exists())

    @unittest.skipUnless(shutil.which("duckdb"), "duckdb CLI is required")
    def test_real_ingestion_and_four_results_per_database_including_empty_jobs(self) -> None:
        self.step("00")
        repositories = [
            "dsvpn/dsvpn", "file/file", "flex/flex",
            "inotify-tools/inotify-tools", "nnn/nnn",
        ]
        archives = []
        for index, repository in enumerate(repositories):
            archive = self.workspace / f"result-{index}.zip"
            archives.append(str(archive))
            results = [
                {
                    "ruleId": "cpp-fprintf-call",
                    "kind": "problem",
                    "locations": [{"physicalLocation": {
                        "artifactLocation": {"uri": "example.c"},
                        "region": {"startLine": line, "startColumn": 1},
                    }}],
                }
                for line in range(7, 0, -1) if index != 2
            ]
            with zipfile.ZipFile(archive, "w") as stream:
                stream.writestr("results.sarif", json.dumps({
                    "version": "2.1.0", "runs": [{"results": results}],
                }))
        state = {"cgamr-submissions": {"sample-05": {
            "status": "succeeded", "user": "bob", "language": "cpp",
            "session_id": "test", "repositories": repositories, "downloads": archives,
        }}}
        self.import_state(state)
        for number in ("15", "16", "17", "18"):
            self.step(number)
        db = self.workspace / "findings/all.duckdb"
        query = (sample_help.INPUTS / "results.sql").read_text()

        def query_rows():
            result = subprocess.run(
                ["duckdb", "-readonly", "-json", str(db)], input=query,
                capture_output=True, text=True, check=True,
            )
            return json.loads(result.stdout)

        rows = query_rows()
        for repository in repositories:
            selected = [row for row in rows if row["repository"] == repository]
            if repository == "flex/flex":
                self.assertEqual(len(selected), 1)
                self.assertEqual(selected[0]["finding_count"], 0)
                self.assertIsNone(selected[0]["finding_number"])
            else:
                self.assertEqual([row["start_line"] for row in selected], [1, 2, 3, 4])
                self.assertTrue(all(row["finding_count"] == 7 for row in selected))
        for archive in archives:
            with zipfile.ZipFile(archive, "w") as stream:
                stream.writestr("results.sarif", '{"version":"2.1.0","runs":[]}')
        self.step("16")
        self.step("17")
        self.assertEqual(len(query_rows()), 5)
        self.assertTrue(all(row["finding_count"] == 0 for row in query_rows()))


if __name__ == "__main__":
    unittest.main()
