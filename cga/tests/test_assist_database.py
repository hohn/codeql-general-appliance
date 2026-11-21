from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile


COLLECTION = Path(__file__).resolve().parents[1]

CODEQL = r"""#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import zipfile
args = sys.argv[1:]
if args[0] == "version":
    print("2.27.1")
elif args[:2] == ["database", "create"]:
    database = Path(args[2])
    source = Path(next(value.split("=", 1)[1] for value in args if value.startswith("--source-root=")))
    if os.environ.get("CGA_TEST_FAIL_VERSION", "\0") in str(source):
        sys.exit("fixed source-version failure")
    command = next((value.split("=", 1)[1] for value in args if value.startswith("--command=")), None)
    if command:
        subprocess.run(shlex.split(command), cwd=source, check=True)
    database.mkdir()
    (database / "codeql-database.yml").write_text("primaryLanguage: cpp\n")
    (database / "identity").write_text(str(source) + "\n" + (source / "input.c").read_text())
    if command:
        (database / "log").mkdir()
        (database / "log/build-tracer.log").write_text("Intercepted call to /usr/bin/cc\n")
elif args[:2] == ["database", "bundle"]:
    output = Path(args[args.index("--output") + 1])
    database = Path(args[-1])
    with zipfile.ZipFile(output, "w") as archive:
        for path in database.rglob("*"):
            if path.is_file():
                archive.write(path, "database/" + str(path.relative_to(database)))
else:
    sys.exit("unexpected CodeQL invocation: " + json.dumps(args))
"""

LLM = r"""#!/usr/bin/env python3
import json
import sys
request = json.loads(sys.argv[-1].rsplit("\n\n", 1)[1])
commands = []
if request["parameters"]["operation"] == "build" and request["previous_attempts"]:
    commands = [[sys.executable, "-c", "from pathlib import Path; Path('dependency').write_text('installed')"]]
print(json.dumps({"commands": commands, "build_command": "./build.sh",
                  "notes": "Read the documented build and repair its dependency after failure."}))
"""


class DatabaseAssistTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="cga-db-assist-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = self.root / "preparation"
        self.environment = {key: value for key, value in os.environ.items()
                            if not key.startswith(("CGA_", "CGAST_"))}
        for name, text in (("codeql", CODEQL), ("llm", LLM)):
            path = self.root / name
            path.write_text(text)
            path.chmod(0o755)
        self.environment["CGA_DB_CODEQL"] = str(self.root / "codeql")
        self.environment["CGA_TMPDIR"] = str(self.root / "scratch")
        self.environment["CGA_PREP_LLM_COMMAND"] = shlex.quote(str(self.root / "llm"))
        self.repository = self.root / "toy"
        self.repository.mkdir()
        self.git("init", "--quiet")
        (self.repository / "input.c").write_text("int main(void) { return 1; }\n")
        (self.repository / "README.md").write_text(
            "Build using ./build.sh. This toy requires the dependency file.\n")
        (self.repository / "build.sh").write_text(
            "#!/bin/sh\n"
            "test -f dependency || { echo 'missing dependency' >&2; exit 6; }\n")
        (self.repository / "build.sh").chmod(0o755)
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.test",
                 "commit", "--quiet", "-m", "pre")
        self.git("tag", "pre")
        (self.repository / "input.c").write_text("int main(void) { return 0; }\n")
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.test",
                 "commit", "--quiet", "-m", "post")
        self.git("tag", "post")
        self.cli("init", str(self.workspace), inside=False)
        self.cli("chain", "start", "--name", "database-build")

    def git(self, *arguments):
        return subprocess.run(
            ["git", "-C", str(self.repository), *arguments], check=True,
            capture_output=True, text=True, env=self.environment)

    def cli(self, *arguments, check=True, inside=True):
        completed = subprocess.run(
            [str(COLLECTION / "cga"),
             *(["-C", str(self.workspace)] if inside else []), *arguments],
            cwd=self.root, env=self.environment, text=True, capture_output=True,
            timeout=45)
        if check:
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        return completed

    def database(self, *arguments, **kwargs):
        return self.cli("a", "d", *arguments, **kwargs)

    def state(self):
        return json.loads(self.cli("--json", "state", "show").stdout)

    def document(self, key):
        path = Path(self.state()[key])
        return json.loads((path if path.is_absolute() else self.workspace / path).read_text())

    def fetch(self, *extra):
        return self.database(
            "fetch", "--git", str(self.repository), "--owner", "local",
            "--repo", "toy", "--language", "cpp", "--ref", "pre=pre",
            "--ref", "post=post", *extra)

    def test_git_matrix_content_identities_resume_export_and_analysis_handoff(self):
        self.fetch()
        self.fetch()
        sources = self.document("cgasp-sources")["items"]
        self.assertEqual({row["resolved_commit"] for row in sources},
                         {self.git("rev-parse", ref).stdout.strip() for ref in ("pre", "post")})
        self.database("build", "--mode", "bm-none", "--mode", "trace",
                      "--command", "/bin/true")
        before = self.document("cgadb-records")
        self.database("build")
        self.assertEqual(before, self.document("cgadb-records"))
        self.database("index")
        destination = self.root / "collection"
        self.database("export", str(destination))
        self.cli("catalog", "verify", "--catalog", str(destination / "metadata.sql"),
                 "--manifest", str(destination / "manifest.json"))
        with sqlite3.connect(destination / "metadata.sql") as db:
            db.row_factory = sqlite3.Row
            rows = [dict(row) for row in db.execute("SELECT * FROM metadata")]
        self.assertEqual(len(rows), 4)
        for row in rows:
            self.assertEqual(row["git_repo"], "toy-" + row["content_hash"])
            archive = destination / "local" / row["git_repo"] / f"local_{row['git_repo']}_db.zip"
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), row["content_hash"])
            self.assertEqual(row["result_url"], archive.as_uri())
        analysis = self.root / "analysis"
        self.cli("init", str(analysis), inside=False)
        for arguments in (
                ("chain", "start", "--name", "analysis"),
                ("dl", "getmeta", str(destination / "metadata.sql")),
                ("dl", "select"),
                ("dl", "download", "--output-dir", str(self.root / "downloaded"))):
            self.cli("-C", str(analysis), *arguments, inside=False)
        self.assertEqual(len(list((self.root / "downloaded/local").glob("*/*_db.zip"))), 4)
        self.assertNotEqual(self.database("export", str(destination), check=False).returncode, 0)
        self.assertFalse(any(key.startswith(("cgadl-", "cgaql-")) for key in self.state()))
        # A later plumbing operation must not be overwritten by the recovery checkpoint.
        intermediate = self.root / "plumbing-export"
        self.cli("catalog", "export", str(intermediate))
        (destination / "metadata.sql").unlink()
        (destination / "manifest.json").unlink()
        self.database("export", str(self.root / "after-plumbing"))

    def test_llm_discovers_build_and_repairs_dependency_with_attempt_evidence(self):
        self.fetch("--use-llm")
        self.database("build", "--mode", "trace", "--use-llm", "--llm-attempts", "2")
        for record in self.document("cgadb-records")["items"]:
            history = record["supervision"]["attempts"]
            self.assertEqual([entry["status"] for entry in history], ["failed", "succeeded"])
            self.assertIn("missing dependency", history[0]["output"])
            self.assertTrue((Path(history[0]["directory"]) / "recipe.json").is_file())
            request = json.loads((Path(history[1]["directory"]) / "request.json").read_text())
            self.assertIn("./build.sh", request["source_context"]["documents"]["README.md"])
            self.assertFalse((Path(record["source_input"]) / "dependency").exists())
            self.assertTrue((Path(record["source"]) / "dependency").is_file())
            self.assertEqual(record["build_command"], "./build.sh")
            self.assertGreater(record["trace_verification"]["intercepted_processes"], 0)
        self.database("index")

    def test_failed_matrix_requires_explicit_partial_index_and_resumes_successes(self):
        self.fetch()
        self.environment["CGA_TEST_FAIL_VERSION"] = "--post"
        result = self.database("build", "--mode", "bm-none", check=False)
        self.assertNotEqual(result.returncode, 0)
        result = self.database("index", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("matrix is incomplete", result.stderr)
        self.database("index", "--allow-partial")
        first = self.document("cgadb-records")["items"]
        self.assertEqual(len(first), 1)
        del self.environment["CGA_TEST_FAIL_VERSION"]
        self.database("build")
        records = self.document("cgadb-records")["items"]
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0], first[0])
        result = self.database("export", str(self.root / "stale"), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "stale").exists())
        self.database("index")

    def test_tar_and_zip_versions_and_changed_sources_are_not_overwritten(self):
        tar = self.root / "pre.tar.gz"
        with tarfile.open(tar, "w:gz") as stream:
            stream.add(self.repository / "input.c", "project/input.c")
        archive = self.root / "post.zip"
        with zipfile.ZipFile(archive, "w") as stream:
            stream.write(self.repository / "input.c", "project/input.c")
        arguments = (
            "fetch", "--archive", f"pre={tar}", "--archive", f"post={archive}",
            "--owner", "local", "--repo", "toy", "--language", "cpp")
        self.database(*arguments)
        sources = self.document("cgasp-sources")["items"]
        self.assertEqual(len(sources), 2)
        self.assertTrue(all(row["archive_sha256"] for row in sources))
        changed = Path(sources[0]["source_dir"]) / "input.c"
        if not changed.is_absolute():
            changed = self.workspace / changed
        changed.write_text("changed source")
        self.assertNotEqual(self.database(*arguments, check=False).returncode, 0)
        self.assertEqual(changed.read_text(), "changed source")

    def test_llm_runner_failure_is_not_a_successful_build(self):
        self.fetch()
        self.environment["CGA_PREP_LLM_COMMAND"] = str(self.root / "missing-runner")
        result = self.database("build", "--mode", "trace", "--use-llm",
                               "--llm-attempts", "1", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot start LLM supervisor", result.stderr)
        self.assertNotEqual(self.database("index", check=False).returncode, 0)


@unittest.skipUnless(shutil.which("duckdb"), "duckdb CLI is required")
class SqliteComparisonTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="cga-sqlite-compare-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.analysis = self.root / "analysis"
        self.analysis.mkdir()
        (self.root / "collection").mkdir()
        self.builds, self.runs = [], []
        for variant in ("vulnerable", "patched"):
            for mode in ("none", "trace"):
                name = f"sqlite-toy-{variant}--{mode}"
                repository = f"owner/{name}"
                self.builds.append({
                    "variant": variant, "mode": mode, "repository": repository,
                })
                self.runs.append({
                    "repository": repository, "status": "succeeded",
                    "finding_count": int(variant == "vulnerable"),
                    "mrva_result_count": int(variant == "vulnerable"),
                    "artifacts": {"sarif": f"/findings/{name}.sarif"},
                })
        self.ingestion = {
            "status": "succeeded", "user": "toy", "session_id": 1,
            "query_pack": "/inputs/injection.tgz", "jobs": self.runs,
        }
        self.duckdb(
            "CREATE TABLE sarif_results "
            "(\"user\" VARCHAR, file_name VARCHAR, rule_id VARCHAR);"
            "INSERT INTO sarif_results VALUES "
            "('toy', 'sqlite-toy-vulnerable--none.sarif', 'cpp/toy-sql-injection'),"
            "('toy', 'sqlite-toy-vulnerable--trace.sarif', 'cpp/toy-sql-injection');")

    def duckdb(self, sql, *, readonly=False):
        result = subprocess.run(
            ["duckdb", "-json", *(["-readonly"] if readonly else []),
             str(self.analysis / "combined.duckdb"), "-c", sql],
            cwd=self.analysis, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else []

    def compare(self):
        (self.root / "collection/manifest.json").write_text(
            json.dumps({"databases": self.builds}))
        (self.analysis / "analysis-state.json").write_text(
            json.dumps({"cgasi-ingestions": {"sqlite-injection": self.ingestion}}))
        query = COLLECTION / "cgaassist/examples/sqlite-toy/compare.sql"
        return self.duckdb(query.read_text(), readonly=True)

    def test_completed_empty_runs_remain_in_the_comparison(self):
        rows = self.compare()
        self.assertEqual(
            [(row["variant"], row["mode"], row["findings"]) for row in rows],
            [("vulnerable", "none", 1), ("vulnerable", "trace", 1),
             ("patched", "none", 0), ("patched", "trace", 0)])
        self.assertTrue(all(row["status"] == "complete" for row in rows))

    def test_missing_run_is_not_reported_as_zero_findings(self):
        self.runs.pop()
        row = self.compare()[-1]
        self.assertEqual(row["status"], "missing/failed job")
        self.assertIsNone(row["findings"])

    def test_missing_build_is_visible(self):
        self.builds.pop()
        row = self.compare()[-1]
        self.assertEqual(row["status"], "missing build")
        self.assertIsNone(row["findings"])

    def test_missing_positive_ingestion_is_a_count_mismatch(self):
        self.duckdb(
            "DELETE FROM sarif_results "
            "WHERE file_name = 'sqlite-toy-vulnerable--none.sarif'")
        row = self.compare()[0]
        self.assertEqual(row["status"], "count mismatch")
        self.assertEqual(row["ingested_findings"], 1)

    def test_failed_mrva_job_is_not_reported_as_zero_findings(self):
        self.runs[-1]["status"] = "failed"
        row = self.compare()[-1]
        self.assertEqual(row["status"], "missing/failed job")
        self.assertIsNone(row["findings"])

    def test_mrva_count_must_match_ingested_findings(self):
        self.runs[-1]["mrva_result_count"] = 1
        self.assertEqual(self.compare()[-1]["status"], "count mismatch")


if __name__ == "__main__":
    unittest.main()
