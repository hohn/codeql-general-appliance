from __future__ import annotations

import argparse
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
CGA_ROOT = PROJECT.parent
REPO_ROOT = CGA_ROOT.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(REPO_ROOT / "cga" / "cgalib"))
from cgacodeql import cli  # noqa: E402


class CgaCodeqlTest(unittest.TestCase):
    def test_check_resolves_bundle_pack(self):
        scratch = CGA_ROOT / "cga-prep-tmp"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as raw, mock.patch.dict(
                "os.environ", {"CGAST_ROOT": str(CGA_ROOT),
                               "CGAST_TMPDIR": raw}, clear=False):
            root = Path(raw) / "codeql"
            binary = root / "codeql"
            binary.parent.mkdir()
            binary.write_bytes(b"binary")
            pack = root / "qlpacks/codeql/cpp-all/12.1.1/qlpack.yml"
            pack.parent.mkdir(parents=True)
            pack.write_text("name: codeql/cpp-all\n")
            state = {}
            with mock.patch.object(
                    cli, "_capture", return_value="2.27.1\n"), \
                    mock.patch.object(cli.platform, "system", return_value="Linux"), \
                    mock.patch.object(cli.platform, "machine", return_value="aarch64"):
                cli.cmd_check(state, argparse.Namespace(
                    codeql=str(binary), version="2.27.1", system="Linux",
                    machine=["aarch64", "arm64"],
                    pack=["codeql/cpp-all@12.1.1"], require_file=[]))
            document = cli.workflow.load_json(
                cli.cgast.resolve(state[cli.CHECK_KEY]))
            self.assertEqual(document["codeql_version"], "2.27.1")
            self.assertEqual(len(document["required_files"]), 1)


if __name__ == "__main__":
    unittest.main()
