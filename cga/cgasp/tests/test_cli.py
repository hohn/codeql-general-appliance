from __future__ import annotations

import argparse
import hashlib
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
CGA_PREP_ROOT = PROJECT.parent
REPO_ROOT = CGA_PREP_ROOT.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(REPO_ROOT / "cga" / "cgalib"))
from cgasp import cli  # noqa: E402


class CgaspTest(unittest.TestCase):
    def test_archive_extraction_verifies_digest_and_rejects_escaping_paths(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "source.zip"
            with zipfile.ZipFile(archive, "w") as stream:
                stream.writestr("project/input.c", "int main(void) { return 0; }\n")
            source = {"url": str(archive),
                      "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
            destination = root / "source"
            self.assertEqual(cli._extract_archive(source, root, destination),
                             source["sha256"])
            self.assertTrue((destination / "input.c").is_file())
            source["sha256"] = "0" * 64
            with self.assertRaisesRegex(cli.workflow.WorkflowError, "SHA-256 mismatch"):
                cli._extract_archive(source, root, root / "bad-hash")
            self.assertFalse((root / "bad-hash").exists())
            with zipfile.ZipFile(archive, "w") as stream:
                stream.writestr("../escaped.c", "escape")
            with self.assertRaisesRegex(cli.workflow.WorkflowError, "escapes"):
                cli._extract_archive({"url": str(archive)}, root, root / "bad-path")
            self.assertFalse((root / "escaped.c").exists())

    def test_dry_run_plans_git_and_dsc_without_commands(self):
        scratch = CGA_PREP_ROOT / "cga-prep-tmp"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as raw, mock.patch.dict(
                "os.environ", {"CGAST_ROOT": str(CGA_PREP_ROOT),
                               "CGAST_TMPDIR": raw}):
            work = Path(raw) / "work.json"
            cli.workflow.write_json(work, {"items": [
                {"id": "CVE-1-vulnerable", "source": {
                    "strategy": "git", "url": "https://example.test/r",
                    "ref": "abc"}, "dependencies": []},
                {"id": "CVE-1-patched", "source": {
                    "strategy": "debian-dsc",
                    "url": "https://example.test/pkg_1.dsc"},
                 "dependencies": [["apt-get", "build-dep", "pkg"]]},
            ]})
            state = {"cgacv-work-items": cli.cgast.rel(work)}
            with mock.patch.object(cli.workflow, "run") as run:
                cli.cmd_fetch(state, argparse.Namespace(
                    output_dir=str(Path(raw) / "sources"), dry_run=True))
            run.assert_not_called()
            plan = cli.workflow.load_json(
                cli.cgast.resolve(state[cli.PLAN_KEY]))
            sources = cli.workflow.load_json(
                cli.cgast.resolve(state[cli.SOURCES_KEY]))
            self.assertEqual(plan["count"], 2)
            self.assertTrue(all(x["status"] == "planned"
                                for x in sources["items"]))

    def test_adopt_hashes_and_registers_local_sources(self):
        scratch = CGA_PREP_ROOT / "cga-prep-tmp"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as raw, mock.patch.dict(
                "os.environ", {"CGAST_ROOT": str(CGA_PREP_ROOT),
                               "CGAST_TMPDIR": raw}):
            source = Path(raw) / "source"
            source.mkdir()
            (source / "input.c").write_text("int main(void) { return 0; }\n")
            manifest = Path(raw) / "sources.json"
            cli.workflow.write_json(manifest, {"items": [{
                "id": "CVE-1-vulnerable",
                "owner": "debian",
                "repo": "pkg-vulnerable",
                "language": "cpp",
                "variant": "vulnerable",
                "version": "1",
                "source_dir": str(source),
                "dependencies": [],
                "build_command": "make",
            }]})
            state = {}
            cli.cmd_adopt(
                state, argparse.Namespace(manifest=str(manifest)))
            adopted = cli.workflow.load_json(
                cli.cgast.resolve(state[cli.SOURCES_KEY]))
            self.assertEqual(adopted["count"], 1)
            self.assertEqual(adopted["items"][0]["status"], "ready")
            self.assertEqual(
                adopted["items"][0]["source_tree_sha256"],
                cli.tree_digest(source))
            self.assertEqual(
                cli.cgast.resolve(adopted["items"][0]["source_dir"]), source)

    def test_adopt_rejects_source_hash_mismatch(self):
        scratch = CGA_PREP_ROOT / "cga-prep-tmp"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as raw, mock.patch.dict(
                "os.environ", {"CGAST_ROOT": str(CGA_PREP_ROOT),
                               "CGAST_TMPDIR": raw}):
            source = Path(raw) / "source"
            source.mkdir()
            manifest = Path(raw) / "sources.json"
            cli.workflow.write_json(manifest, {"items": [{
                "id": "CVE-1-vulnerable",
                "source_dir": str(source),
                "source_tree_sha256": "0" * 64,
            }]})
            with self.assertRaisesRegex(
                    cli.workflow.WorkflowError, "source tree hash mismatch"):
                cli.cmd_adopt(
                    {}, argparse.Namespace(manifest=str(manifest)))


if __name__ == "__main__":
    unittest.main()
