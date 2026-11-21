from __future__ import annotations

import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import pty
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


COLLECTION = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(COLLECTION / name) for name in (
    "cgaassist", "cgalib", "cgabench", "cgadl", "cgaql", "cgawf", "cgasi", "cgauv",
)]

from cgaassist import cli as assist
from cgadl.catalog import COLUMNS
from workflow import WorkflowError


FAKE_CODEQL = """#!/usr/bin/env python3
import json
from pathlib import Path
import sys
args = sys.argv[1:]
if args[:2] == ["pack", "install"]:
    Path("codeql-pack.lock.yml").write_text("dependencies: {}\\n")
elif args[:2] == ["database", "unbundle"]:
    target = next(value.split("=", 1)[1] for value in args if value.startswith("--target="))
    name = next(value.split("=", 1)[1] for value in args if value.startswith("--name="))
    root = Path(target) / name
    root.mkdir(parents=True)
    (root / "codeql-database.yml").write_text("primaryLanguage: cpp\\n")
elif args[:2] == ["query", "compile"]:
    assert "--check-only" in args
    if "BROKEN" in Path(args[-1]).read_text():
        sys.stderr.write("invalid QL draft\\n")
        sys.exit(2)
else:
    sys.stderr.write("unexpected CodeQL invocation: " + json.dumps(args))
    sys.exit(3)
"""


class AssistTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cga-assist-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = self.root / "authoring workspace"
        self.library = self.root / "permanent queries"
        self.environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("CGA_", "CGAST_"))
        }
        executable = self.root / "codeql"
        executable.write_text(FAKE_CODEQL)
        executable.chmod(0o755)
        dependency = self.root / "qlpacks/codeql/cpp-all/1.2.3/qlpack.yml"
        dependency.parent.mkdir(parents=True)
        dependency.write_text("version: 1.2.3\n")
        self.environment["CGA_CGAQL_CODEQL"] = str(executable)
        self.metadata = self.root / "metadata.sql"
        with closing(sqlite3.connect(self.metadata)) as connection, connection:
            connection.execute("CREATE TABLE metadata (" + ",".join(COLUMNS) + ")")
            for index, language in enumerate(("cpp", "cpp", "cpp", "python"), 1):
                archive = self.root / f"database-{index}.zip"
                with zipfile.ZipFile(archive, "w") as stream:
                    stream.writestr("database/codeql-database.yml", "primaryLanguage: cpp\n")
                row = dict.fromkeys(COLUMNS, "")
                row.update(
                    content_hash=hashlib.sha256(archive.read_bytes()).hexdigest(),
                    git_owner=f"owner{index}", git_repo=f"repo{index}",
                    primary_language=language, result_url=archive.as_uri(),
                    tool_name="codeql", tool_version="2.27.1",
                    db_file_size=archive.stat().st_size,
                )
                connection.execute(
                    "INSERT INTO metadata VALUES (" + ",".join("?" for _ in COLUMNS) + ")",
                    [row[column] for column in COLUMNS],
                )

    def cli(self, *args: str, check=True, inside=True):
        prefix = ["-C", str(self.workspace)] if inside else []
        result = subprocess.run(
            [COLLECTION / "cga", *prefix, *args], cwd=self.root,
            env=self.environment, capture_output=True, text=True, timeout=30,
        )
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def query(self, *args: str, **kwargs):
        return self.cli("a", "q", *args, **kwargs)

    def state(self):
        return json.loads(self.cli("--json", "state", "show").stdout)

    def begin(self):
        self.query("start", str(self.workspace), inside=False)
        self.query("catalogue", str(self.metadata))

    def prepare(self):
        self.begin()
        self.query("select-databases", "--rows", "1", "2", "3")
        self.query("download")
        self.query("prepare", "--databases", "owner1/repo1", "owner2/repo2")
        return Path(self.state()[assist.KEY]["working_tree"])

    def test_help_aliases_and_nested_completion_are_read_only(self):
        before = set(self.root.iterdir())
        for suffix in (("-h",), ("prepare", "-h"), ("publish", "--help")):
            long = self.cli("assist", "query-writing", *suffix, inside=False)
            short = self.query(*suffix, inside=False)
            self.assertEqual(short.stdout, long.stdout)
        for suffix in (("-h",), ("fetch", "-h"), ("build", "--help")):
            long = self.cli("assist", "database-build", *suffix, inside=False)
            short = self.cli("a", "d", *suffix, inside=False)
            self.assertEqual(short.stdout, long.stdout)
        self.assertEqual(set(self.root.iterdir()), before)
        for words, index, expected in (
            ("a ''", 2, {"q", "query-writing", "d", "database-build"}),
            ("a d ''", 3, {"fetch", "build", "index", "export"}),
            ("assist database-build build --", 4, {"--use-llm", "--mode", "--command"}),
            ("a q ''", 3, {"start", "prepare", "save", "publish"}),
            ("assist query-writing prepare --", 4, {"--databases"}),
            ("a q publish --", 4, {"--name"}),
        ):
            result = subprocess.run(
                ["bash", "-c",
                 f'source "$1"; COMP_WORDS=("$2" {words}); COMP_CWORD={index}; '
                 '_cga; printf "%s\\n" "${COMPREPLY[@]}"',
                 "_", str(COLLECTION / "completions/cga.bash"), str(COLLECTION / "cga")],
                env=self.environment, capture_output=True, text=True, check=True,
            )
            self.assertTrue(expected <= set(result.stdout.splitlines()), result.stdout)

    def test_selection_validation_and_fixed_editor_databases(self):
        self.begin()
        self.assertEqual(list(Path(self.state()[assist.KEY]["qlibdir"]).iterdir()), [])
        for rows in (("1",), ("1", "1"), ("1", "4"), ("1", "99")):
            result = self.query("select-databases", "--rows", *rows, check=False)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertNotIn("cgadl-selection", self.state())
        self.query("select-databases", "--search", "owner1", "--rows", "1", "2")
        self.query("download")
        for databases in (("owner1/repo1",), ("owner1/repo1", "owner3/repo3")):
            result = self.query("prepare", "--databases", *databases, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(Path(self.state()[assist.KEY]["working_tree"]).exists())
        self.query("prepare", "--databases", "owner1/repo1", "owner2/repo2")
        for command in (("catalogue", str(self.metadata)), ("select-databases", "--rows", "2", "3")):
            self.assertNotEqual(self.query(*command, check=False).returncode, 0)
        self.assertNotEqual(
            self.query("start", str(self.workspace), inside=False, check=False).returncode, 0)

    def test_drafts_compile_gate_durable_publication_and_collision_checks(self):
        working = self.prepare()
        workspace = json.loads((working / "query.code-workspace").read_text())
        self.assertEqual(workspace["folders"][0]["path"], ".")
        databases = self.state()[assist.KEY]["editor_databases"]
        self.assertEqual(len(databases), 2)
        self.assertTrue(all((Path(row["directory"]) / "codeql-database.yml").is_file()
                            for row in databases))
        (working / "support").mkdir()
        (working / "support/Helper.qll").write_text("import cpp\n")
        source = working / "Fprintf.ql"
        original = source.read_text()
        source.write_text(original + "\nBROKEN\n")
        self.query("save", "NewQuery")
        first = self.state()[assist.KEY]["saved"]["NewQuery"]
        result = self.query("publish", str(self.library), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid QL draft", result.stderr)
        self.assertFalse(self.library.exists())
        self.assertIn("BROKEN", (Path(first["directory"]) / "NewQuery.ql").read_text())
        self.cli("ql", "select", "id", "cpp/newquery")
        source.write_text(original)
        self.query("save", "NewQuery")
        self.assertNotIn("cgaql-selection", self.state())
        self.assertIn("BROKEN", (Path(first["directory"]) / "NewQuery.ql").read_text())
        self.cli("ql", "select", "id", "cpp/newquery")
        source.write_text(original + "\nBROKEN\n")
        self.query("publish", str(self.library))
        published = self.library / "NewQuery/NewQuery.ql"
        self.assertNotIn("BROKEN", published.read_text())
        self.assertIn("@id cpp/newquery", published.read_text())
        self.assertTrue((published.parent / "support/Helper.qll").is_file())
        self.assertFalse((published.parent / "databases").exists())
        self.assertFalse((published.parent / "query.code-workspace").exists())
        state = self.state()
        self.assertNotIn("cgaql-selection", state)
        self.assertEqual(state["cgaql-querydir"], str(self.library))
        index = self.workspace / state["cgaql-index"]
        with closing(sqlite3.connect(index)) as connection:
            paths = [row[0] for row in connection.execute("SELECT path FROM queries")]
        self.assertEqual(paths, [str(published)])
        listed = self.cli("ql", "list", "5")
        self.assertIn("cpp/newquery", listed.stdout + listed.stderr)
        before = published.read_bytes()
        result = self.query("publish", str(self.library), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(published.read_bytes(), before)
        source.write_text(original.replace("@id cpp-fprintf-call", "@id cpp/newquery"))
        self.query("save", "Duplicate")
        result = self.query("publish", str(self.library), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)
        self.assertFalse((self.library / "Duplicate").exists())
        source.write_text(original.replace("@id cpp-fprintf-call", "@id cpp-fprintf-call-custom"))
        self.query("save", "Custom")
        saved = self.state()[assist.KEY]["saved"]["Custom"]
        self.assertIn("@id cpp-fprintf-call-custom",
                      (Path(saved["directory"]) / "Custom.ql").read_text())

    def test_prompt_choices_and_failed_index_restore_previous_draft(self):
        working = self.prepare()
        self.query("save", "Draft")
        state = self.state()
        record = state[assist.KEY]
        target = Path(record["qlibdir"]) / "Draft/Draft.ql"
        previous = target.read_bytes()
        (working / "Fprintf.ql").write_text("BROKEN")
        args = assist.build_parser().parse_args(["q", "save", "Draft"])
        with mock.patch.object(assist, "tool", side_effect=WorkflowError("index failed")):
            with self.assertRaisesRegex(WorkflowError, "index failed"):
                assist.save(state, args)
        self.assertEqual(target.read_bytes(), previous)
        with mock.patch.object(assist, "prompt", return_value="1 2"):
            chosen = assist.editor_databases(state, None)
        self.assertEqual(
            [row["git_repo"] for row in chosen],
            ["repo1-" + chosen[0]["content_hash"], "repo2-" + chosen[1]["content_hash"]])
        with mock.patch("builtins.open", side_effect=OSError("no terminal")):
            with self.assertRaisesRegex(WorkflowError, "explicit argument"):
                assist.prompt("Choice")

    def test_multiple_versions_of_one_upstream_repository_have_distinct_editor_inputs(self):
        archive = self.root / "database-3.zip"
        with zipfile.ZipFile(archive, "a") as stream:
            stream.writestr("database/version.txt", "another source version")
        with closing(sqlite3.connect(self.metadata)) as connection, connection:
            connection.execute(
                "UPDATE metadata SET git_owner='owner1', git_repo='repo1', "
                "content_hash=?, db_file_size=? WHERE rowid=3",
                (hashlib.sha256(archive.read_bytes()).hexdigest(), archive.stat().st_size))
        self.begin()
        self.query("select-databases", "--rows", "1", "3")
        self.query("download")
        state = self.state()
        rows = assist.selection.read_selection(Path(state["cgadl-selection"]))
        identities = [f"{row['git_owner']}/{row['git_repo']}" for row in rows]
        self.assertEqual(len(set(identities)), 2)
        result = self.query(
            "prepare", "--databases", "owner1/repo1", "owner1/repo1", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ambiguous", result.stderr)
        self.query("prepare", "--databases", *identities)
        self.assertEqual(len(self.state()[assist.KEY]["editor_databases"]), 2)

    def test_prompt_reads_a_real_nonseekable_terminal(self):
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        os.write(master, b"1 2\n")
        with mock.patch("builtins.open",
                        side_effect=lambda _path, mode: os.fdopen(os.dup(slave), mode)):
            self.assertEqual(assist.prompt("Choose database numbers"), "1 2")


if __name__ == "__main__":
    unittest.main()
