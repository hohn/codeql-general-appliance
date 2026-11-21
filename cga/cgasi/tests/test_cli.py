from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
CGA_ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(CGA_ROOT / "cgalib"))

from cgasi import cli, serve, store  # noqa: E402


def sarif(rule_id: str, uri: str) -> bytes:
    value = {
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"rules": [{
                "id": rule_id,
                "name": rule_id,
                "properties": {"kind": "problem", "name": rule_id},
            }]}},
            "results": [{
                "ruleId": rule_id,
                "kind": "problem",
                "locations": [{"physicalLocation": {
                    "artifactLocation": {"uri": uri},
                    "region": {"startLine": 7, "startColumn": 3},
                }}],
            }],
        }],
    }
    return json.dumps(value).encode("utf-8")


def empty_sarif() -> bytes:
    value = {
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "empty-ingestion-test", "rules": []}},
            "results": [],
        }],
    }
    return json.dumps(value).encode("utf-8")


def archive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as output:
        output.writestr("results.sarif", payload)


class ViewTest(unittest.TestCase):
    def test_findings_section_is_distinct_without_a_database(self) -> None:
        state = {"cgasi-ingestions": {"bob-1": {
            "user": "bob", "session_id": 1, "jobs": [{}],
            "finding_count": 0,
        }}}
        with mock.patch.object(serve.cgast, "load_session",
                               return_value=state):
            detail = serve.detail_fragment()
        self.assertIn("<h3>Ingestions</h3>", detail)
        self.assertIn("<h3>Findings</h3>", detail)
        self.assertIn("No cumulative database yet", detail)
        self.assertNotIn(">no results<", detail)

    def test_view_command_sets_erc_and_filters(self) -> None:
        state: dict = {}
        args = argparse.Namespace(
            erc=40, user="bob", rule="cpp/.*", kind=None, uri=None,
            line=None, clear=False)
        cli.cmd_view(state, args)
        self.assertEqual(state[cli.VIEW_KEY]["erc"], 40)
        self.assertEqual(state[cli.VIEW_KEY]["filters"],
                         {"user": "bob", "rule": "cpp/.*"})

        clear_args = argparse.Namespace(
            erc=None, user="", rule=None, kind=None, uri=None,
            line=None, clear=False)
        cli.cmd_view(state, clear_args)
        self.assertNotIn("user", state[cli.VIEW_KEY]["filters"])
        self.assertEqual(state[cli.VIEW_KEY]["erc"], 40)

    def test_default_view_shows_ten_and_all(self) -> None:
        erc, filters = serve._view({})
        self.assertEqual(erc, store.DEFAULT_ERC)
        self.assertEqual(erc, 10)
        self.assertEqual(filters,
                         {label: "" for label in store.FILTER_ORDER})


@unittest.skipUnless(shutil.which("duckdb"), "duckdb CLI is required")
class LifecycleTest(unittest.TestCase):
    def test_named_ingestion_accepts_an_empty_result_set(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            result_zip = root / "downloads" / "empty.zip"
            archive(result_zip, empty_sarif())
            state = {"cgamr-submissions": {"empty-1": {
                "user": "nobody", "session_id": 1,
                "status": "succeeded", "language": "cpp",
                "pack": "empty.tgz", "repositories": ["acme/empty"],
                "downloads": [str(result_zip)],
            }}}

            cli.cmd_ingest(state, argparse.Namespace(
                name="empty-1", output_dir=str(root / "ingest")))

            ingestion = state[cli.INGESTIONS_KEY]["empty-1"]
            self.assertEqual(ingestion["finding_count"], 0)
            sqlite = cli.cgast.resolve(
                ingestion["jobs"][0]["artifacts"]["sqlite"])
            with sqlite3.connect(sqlite) as connection:
                self.assertEqual(
                    connection.execute(
                        "select count(*) from sarif_results").fetchone(),
                    (0,),
                )
            self.assertEqual(store.count(Path(state[cli.DB_KEY])), 0)
            cli.cmd_verify(state, argparse.Namespace(names=["empty-1"]))

    def test_named_ingestions_build_one_user_queryable_database(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            bob_zip = root / "downloads" / "bob.zip"
            eve_zip = root / "downloads" / "eve.zip"
            archive(bob_zip, sarif("cpp/bob-rule", "bob.cc"))
            archive(eve_zip, sarif("cpp/eve-rule", "eve.cc"))
            state = {"cgamr-submissions": {
                "bob-1": {
                    "user": "bob", "session_id": 1,
                    "status": "succeeded", "language": "cpp",
                    "pack": "bob.tgz", "repositories": ["acme/bob"],
                    "downloads": [str(bob_zip)],
                },
                "eve-1": {
                    "user": "eve", "session_id": 2,
                    "status": "succeeded", "language": "cpp",
                    "pack": "eve.tgz", "repositories": ["acme/eve"],
                    "downloads": [str(eve_zip)],
                },
            }}
            args = lambda name: argparse.Namespace(  # noqa: E731
                name=name, output_dir=str(root / "ingest"))

            cli.cmd_ingest(state, args("bob-1"))
            cli.cmd_ingest(state, args("eve-1"))

            bob = state[cli.INGESTIONS_KEY]["bob-1"]
            self.assertEqual(bob["finding_count"], 1)
            self.assertEqual(bob["language"], "cpp")
            self.assertEqual(bob["query_pack"], "bob.tgz")
            self.assertEqual(bob["jobs"][0]["repository"], "acme/bob")
            self.assertEqual(bob["jobs"][0]["finding_count"], 1)
            self.assertEqual(
                set(bob["jobs"][0]["artifacts"]),
                {"archive", "sarif", "sqlite"},
            )

            database = Path(state[cli.DB_KEY])
            self.assertEqual(store.count(database), 2)
            self.assertIn("user", store.keys(database))
            self.assertEqual(
                [row["rule_id"] for row in store.select(
                    database, [("user", "bob")])],
                ["cpp/bob-rule"],
            )
            self.assertEqual(
                [row["rule_id"] for row in store.select(
                    database, [("user", "eve")])],
                ["cpp/eve-rule"],
            )
            cli.cmd_verify(
                state, argparse.Namespace(names=["bob-1", "eve-1"]))

            with mock.patch.object(cli.cgast, "read", return_value=state), \
                 mock.patch.object(cli.cgast, "write") as write:
                self.assertEqual(cli.main(["search", "user", "bob"]), 0)
                write.assert_called_once_with(state)

            with mock.patch.object(serve.cgast, "load_session",
                                   return_value=state):
                overview = serve.overview_fragment()
                detail = serve.detail_fragment()
            self.assertIn("bob", overview)
            self.assertIn("eve", overview)
            self.assertIn("cpp/bob-rule", detail)
            self.assertIn("cpp/eve-rule", detail)

            # ERC chooser: a <select> with the default (10) preselected, plus
            # the apply button that posts the assembled command to cgamx cmd.
            self.assertIn('<option value="10" selected>10</option>', detail)
            self.assertIn('data-view-field="erc"', detail)
            self.assertIn('class="cga-apply"', detail)

            # store.find honours per-column regexes and the ERC limit.
            database = Path(state[cli.DB_KEY])
            only_bob = store.find(database, {"user": "^bob$"}, 10)
            self.assertEqual([r["rule_id"] for r in only_bob], ["cpp/bob-rule"])
            self.assertEqual(store.find(database, {"rule": "eve"}, 10)[0]["user"],
                             "eve")
            self.assertEqual(len(store.find(database, {}, 1)), 1)

            # A regex filter set via the CGAST narrows the rendered Findings.
            state[cli.VIEW_KEY] = {"erc": 10, "filters": {"user": "^bob$"}}
            with mock.patch.object(serve.cgast, "load_session",
                                   return_value=state):
                filtered = serve.detail_fragment()
            self.assertIn("cpp/bob-rule", filtered)
            self.assertNotIn("cpp/eve-rule", filtered)
            self.assertIn('value="^bob$"', filtered)


if __name__ == "__main__":
    unittest.main()
