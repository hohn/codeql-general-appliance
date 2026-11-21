from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


COLLECTION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(COLLECTION / "cgalib"))

from command_help import topics
from dispatcher_help import specification


class CommandHelpTest(unittest.TestCase):
    def environment(self, root: Path) -> dict[str, str]:
        env = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("CGA_", "CGAST_", "CGACTL_", "MRVA_"))
        }
        env.update({
            "PYTHON_COLORS": "0",
            "CGA_TMPDIR": str(root / "scratch"),
            "CGA_RUN_DIR": str(root / "services"),
            "CGA_UV_RUN_DIR": str(root / "unified"),
            "CGA_PREP_RUN_DIR": str(root / "prep-services"),
            "MRVA_WORK_DIR": str(root / "mrva"),
            "MRVA_TMP_DIR": str(root / "mrva-services"),
        })
        return env

    def help(self, path: tuple[str, ...], root: Path, env: dict[str, str]) -> str:
        result = subprocess.run(
            [COLLECTION / "cga", *path, "-h"],
            cwd=root, env=env, input="", text=True,
            capture_output=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def test_every_public_help_topic_has_consistent_sections_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            env = self.environment(root)
            for path, topic in topics().items():
                if path == ("uv", "serve"):
                    continue  # Internal foreground server, not a dispatcher action.
                with self.subTest(command=" ".join(("cga", *path))):
                    text = self.help(path, root, env)
                    sections = [
                        "Name:", "Synopsis:", "Description:", "Example:",
                    ]
                    offsets = [text.index(section) for section in sections]
                    self.assertEqual(offsets, sorted(offsets))
                    self.assertIn(
                        " ".join(topic.summary.split()), " ".join(text.split()),
                    )
                    if topic.environment:
                        self.assertIn("Environment Variables:", text)
                        self.assertLess(
                            text.index("Description:"),
                            text.index("Environment Variables:"),
                        )
                    self.assertNotIn("\x1b[", text)
            self.assertEqual(list(root.iterdir()), [])

    def test_dispatcher_aliases_share_documented_help(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            env = self.environment(root)
            for short, long, _tool, *_commands in specification():
                if short == long:
                    continue
                with self.subTest(alias=long):
                    self.assertEqual(
                        self.help((short,), root, env),
                        self.help((long,), root, env),
                    )

    def test_getting_started_aliases_are_identical_and_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            env = self.environment(root)
            for args in (("init",), ("chain", "start", "--name", "getting-started-help")):
                subprocess.run(
                    [COLLECTION / "cga", *args], cwd=root, env=env,
                    check=True, capture_output=True, text=True,
                )
            before = {
                path.relative_to(root): path.read_bytes()
                for path in root.rglob("*") if path.is_file()
            }
            outputs = []
            for args in (
                ("help", "getting-started"), ("help", "getting-started", "-h"),
                ("-h", "-s"), ("-hs",), ("-s", "-h"), ("--help", "-s"),
            ):
                result = subprocess.run(
                    [COLLECTION / "cga", *args], cwd=root, env=env,
                    check=True, capture_output=True, text=True,
                )
                outputs.append(result.stdout)
                self.assertEqual(result.stderr, "")
            self.assertTrue(all(output == outputs[0] for output in outputs))
            self.assertIn("Commands:", outputs[0])
            self.assertIn("cga/mrva-flow/databases.sql", outputs[0])
            self.assertIn("cga mx reset", outputs[0])
            commands = "\n".join(line.strip() for line in outputs[0].splitlines())
            self.assertIn("cga mx start\ncga serve start\ncga serve status", commands)
            self.assertIn("http://127.0.0.1:8599/", outputs[0])
            self.assertIn("cga serve stop\ncga mx check\ncga mx stop", commands)
            self.assertNotIn("cga run start", outputs[0])
            self.assertNotIn("cga uv start", outputs[0])
            self.assertIn("cga si verify first-run", outputs[0])
            self.assertIn("cga ex llm", outputs[0])
            self.assertEqual(before, {
                path.relative_to(root): path.read_bytes()
                for path in root.rglob("*") if path.is_file()
            })
            self.assertEqual({path.name for path in root.iterdir()}, {".cga"})
            for args in (
                ("-s",), ("help", "getting-started", "--unknown"),
                ("help", "--export", str(root / "bad.html"), "getting-started"),
            ):
                with self.subTest(arguments=args):
                    result = subprocess.run(
                        [COLLECTION / "cga", *args], cwd=root, env=env,
                        capture_output=True, text=True,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("error:", result.stderr)
            self.assertFalse((root / "bad.html").exists())

    def test_nested_help_does_not_record_attempts_or_start_services(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            env = self.environment(root)
            for args in (("init",), ("chain", "start", "--name", "help-test")):
                subprocess.run(
                    [COLLECTION / "cga", *args], cwd=root, env=env,
                    check=True, capture_output=True, text=True,
                )
            before = {
                path.relative_to(root): path.read_bytes()
                for path in root.rglob("*") if path.is_file()
            }
            for path in (
                ("dl", "select"), ("ql", "pack"), ("mr", "submit"),
                ("mx", "reset"), ("db", "build"), ("cv", "import"),
                ("ctl", "measure", "--cgast-filter"),
                ("run", "start"), ("serve", "start"), ("uv", "start"),
                ("mu", "serve"), ("sv", "serve"),
            ):
                with self.subTest(command=path):
                    self.help(path, root, env)
            after = {
                path.relative_to(root): path.read_bytes()
                for path in root.rglob("*") if path.is_file()
            }
            self.assertEqual(before, after)
            self.assertEqual({path.name for path in root.iterdir()}, {".cga"})

    @unittest.skipUnless(sys.version_info >= (3, 14), "native argparse colors require Python 3.14")
    def test_shared_headings_use_native_colors(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            env = {**self.environment(root), "PYTHON_COLORS": "1"}
            for path in (
                ("init",), ("dl", "select"), ("run", "start"),
                ("help", "getting-started"),
            ):
                with self.subTest(command=path):
                    text = self.help(path, root, env)
                    headings = ["Name", "Synopsis", "Description", "Example"]
                    if topics()[path].environment:
                        headings.append("Environment Variables")
                    for heading in headings:
                        self.assertRegex(text, rf"\x1b\[[0-9;]+m{re.escape(heading)}:")


if __name__ == "__main__":
    unittest.main()
