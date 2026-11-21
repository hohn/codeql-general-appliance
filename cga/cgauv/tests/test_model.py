from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
CGA_ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(CGA_ROOT / "cgawf"))
sys.path.insert(0, str(CGA_ROOT / "cgalib"))

from cgauv.model import (  # noqa: E402
    collection_model,
    flow_source_path,
    outline_model,
    search_model,
    step_detail,
    workflow_model,
)
from cgawf.repository import Repository, WorkflowError  # noqa: E402
from cgawf.tags import normalize  # noqa: E402
from vid import Space  # noqa: E402


class ModelTest(unittest.TestCase):
    def _repository_with_collections(self, raw: str) -> Repository:
        root = Path(raw) / "workflow"
        repository = Repository.init(root)
        chain_id = repository.start_chain(name="main")
        databases = root / "databases.json"
        databases.write_text(json.dumps({
            "version": 1,
            "count": 2,
            "databases": [
                {
                    "git_owner": "acme",
                    "git_repo": "one",
                    "primary_language": "cpp",
                    "tool_version": "1",
                    "db_file_size": 10,
                },
                {
                    "git_owner": "acme",
                    "git_repo": "two",
                    "primary_language": "python",
                    "tool_version": "2",
                    "db_file_size": 20,
                },
            ],
        }))
        queries = root / "queries.json"
        queries.write_text(json.dumps({
            "version": 1,
            "count": 1,
            "queries": [
                {
                    "id": "q/one",
                    "name": "One",
                    "language": "cpp",
                    "kind": "problem",
                    "severity": "warning",
                    "relpath": "One.ql",
                    "file_size": 30,
                },
            ],
        }))
        with repository.locked():
            manifest = repository.load_manifest()
            _, chain = repository.resolve_chain(manifest, chain_id)
            repository.record_state(
                manifest,
                chain_id,
                chain,
                {"cgadl-selection": str(databases)},
                ["cga", "dl", "sql"],
                "flow",
                tags=normalize([
                    "user:viewable",
                    "subject:database-selection",
                ]),
            )
        with repository.locked():
            manifest = repository.load_manifest()
            _, chain = repository.resolve_chain(manifest, chain_id)
            repository.record_state(
                manifest,
                chain_id,
                chain,
                {
                    "cgadl-selection": str(databases),
                    "cgaql-selection": str(queries),
                },
                ["cga", "ql", "select"],
                "flow",
                tags=normalize([
                    "audience:user",
                    "subject:query-selection",
                ]),
            )
        return repository

    def test_model_groups_steps_and_exposes_detail(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "workflow"
            repository = Repository.init(root)
            chain_id = repository.start_chain(name="main")
            transcript = repository.store().put(b"preflight complete\n")
            with repository.locked():
                manifest = repository.load_manifest()
                _, chain = repository.resolve_chain(manifest, chain_id)
                node_id = repository.record_state(
                    manifest,
                    chain_id,
                    chain,
                    {"cgamx": {"last_phase": "preflight"}},
                    ["cga", "mx", "preflight"],
                    "mrva-flow",
                    {
                        "started_at": "2026-01-01T00:00:00+00:00",
                        "finished_at": "2026-01-01T00:00:01+00:00",
                        "duration_seconds": 1,
                        "exit_code": 0,
                        "transcript": transcript,
                    },
                    {
                        "path": "mrva-flow.sh",
                        "start_line": 80,
                        "end_line": 80,
                        "excerpt": "cga mx preflight",
                    },
                )
            model = workflow_model(repository)
            self.assertEqual(model["chain"]["id"], chain_id)
            self.assertEqual(model["stages"][0]["id"], "infrastructure")
            self.assertEqual(model["stages"][0]["steps"][0]["id"], node_id)
            detail = step_detail(repository, node_id)
            self.assertEqual(detail["transcript"], "preflight complete\n")
            self.assertEqual(
                detail["state_delta"]["added"]["cgamx"]["last_phase"],
                "preflight",
            )
            self.assertEqual(detail["source"]["excerpt"], "cga mx preflight")

    def test_failed_attempt_is_a_pseudo_step(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "workflow"
            repository = Repository.init(root)
            chain_id = repository.start_chain(name="main")
            with repository.locked():
                manifest = repository.load_manifest()
                attempt_id = repository.record_attempt(
                    manifest,
                    chain_id,
                    ["cga", "mr", "run"],
                    "mrva-flow",
                    {
                        "started_at": "2026-01-01T00:00:00+00:00",
                        "finished_at": "2026-01-01T00:00:01+00:00",
                        "duration_seconds": 1,
                        "exit_code": 1,
                    },
                    error="command exited with status 1",
                )
            model = workflow_model(repository)
            step = model["stages"][0]["steps"][0]
            self.assertEqual(step["id"], attempt_id)
            self.assertEqual(step["status"], "failed")
            self.assertEqual(step["stage"], "execution")
            detail = step_detail(repository, attempt_id)
            self.assertEqual(detail["state_delta"], {
                "added": {},
                "updated": {},
                "removed": {},
            })

    def test_outline_collections_search_and_pagination(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repository = self._repository_with_collections(raw)
            databases = collection_model(
                repository,
                "databases",
                filters={"primary_language": "cpp"},
                limit=1,
            )
            self.assertEqual(databases["page"]["total"], 1)
            self.assertEqual(databases["items"][0]["_id"], "acme/one")
            self.assertIn(
                "audience:user",
                databases["tags"]["canonical"],
            )
            outline = outline_model(repository)
            self.assertEqual(outline["schema"], "cga.use.outline.v1")
            self.assertEqual(outline["collections"]["databases"]["total"], 2)
            self.assertEqual(outline["collections"]["queries"]["total"], 1)
            search = search_model(
                repository,
                "acme/two",
                ["audience:user"],
                ["database"],
                limit=10,
            )
            self.assertEqual(search["page"]["total"], 1)
            self.assertEqual(search["results"][0]["id"], "acme/two")

    def test_collection_vids_keep_original_ordinals_and_ignore_mutated_source_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repository = self._repository_with_collections(raw)
            page = collection_model(repository, "databases", query="acme/two", sort_key="git_repo")
            row = page["items"][0]
            self.assertTrue(row["vid"].endswith(",2"))
            before = Space(repository).inspect(row["vid"])
            (repository.root / "databases.json").write_text('{"databases": []}')
            self.assertEqual(collection_model(repository, "databases", query="acme/two")[
                "items"][0]["vid"], row["vid"])
            self.assertEqual(Space(repository).inspect(row["vid"]), before)
            self.assertEqual(before["properties"]["git_repo"], "two")
            with repository.locked():
                manifest = repository.load_manifest()
                chain_id, chain = repository.resolve_chain(manifest, None)
                state = repository.current_state(manifest)
                state["cgadl-selection"] = str(repository.root / "unretained.json")
                repository.record_state(manifest, chain_id, chain, state,
                                        ["cga", "dl", "select"], "test")
            with self.assertRaisesRegex(WorkflowError, "no retained immutable artifact"):
                collection_model(repository, "databases")

    def test_static_frontend_contains_no_mutation_request(self) -> None:
        script = (PROJECT / "cgauv" / "static" / "cgauv.js").read_text()
        self.assertNotIn('method: "POST"', script)
        self.assertNotIn("/run", script)
        page = (PROJECT / "cgauv" / "static" / "index.html").read_text()
        self.assertIn("CGA Unified View", page)
        self.assertIn("Command transcript", page)
        self.assertIn('id="collapse-all"', page)
        self.assertIn('id="collapse-system"', page)
        self.assertIn('aria-controls="system-body"', page)
        self.assertIn('id="detail-heading"', page)
        self.assertIn('id="workflow-splitter"', page)
        self.assertIn('id="detail-splitter"', page)
        self.assertIn('id="workflow-search"', page)
        self.assertIn('id="show-databases"', page)
        self.assertIn('id="show-queries"', page)
        self.assertIn('id="source-link"', page)
        self.assertIn('<select id="theme-select" aria-label="theme">', page)
        self.assertIn('<option value="font-on-white">font on white</option>', page)
        self.assertIn('<option value="minimalist-bw">minimalist b&amp;w</option>', page)
        self.assertIn('data-theme="dark"', page)
        self.assertIn('localStorage.getItem(THEME_STORAGE_KEY)', script)
        style = (PROJECT / "cgauv" / "static" / "cgauv.css").read_text()
        self.assertIn(':root[data-theme="light"]', style)
        self.assertIn("--terminal-bg: #f5f7fa", style)

    def test_secret_tags_are_redacted_from_outline_and_search(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "workflow"
            repository = Repository.init(root)
            chain_id = repository.start_chain(name="main")
            with repository.locked():
                manifest = repository.load_manifest()
                _, chain = repository.resolve_chain(manifest, chain_id)
                repository.record_state(
                    manifest,
                    chain_id,
                    chain,
                    {"secret": "value"},
                    ["cga", "test", "secret"],
                    "flow",
                    tags=normalize([
                        "audience:user",
                        "sensitivity:secret",
                    ]),
                )
            redacted = outline_model(repository)
            self.assertEqual(redacted["redacted_steps"], 1)
            self.assertEqual(redacted["stages"], [])
            included = outline_model(repository, include_sensitive=True)
            self.assertEqual(included["redacted_steps"], 0)
            self.assertEqual(len(included["stages"][0]["steps"]), 1)
            search = search_model(repository)
            self.assertEqual(search["page"]["redacted"], 1)
            self.assertEqual(search["results"], [])

    def test_flow_view_metadata_controls_stage_grouping(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "workflow"
            repository = Repository.init(root)
            (root / "flow-view.json").write_text(json.dumps({
                "schema": "cga.flow-view.v1",
                "id": "test",
                "label": "Test",
                "source": "flow.sh",
                "stages": [
                    {
                        "id": "custom",
                        "label": "Custom stage",
                        "match": [{"tool": ["test"]}],
                    }
                ],
            }))
            (root / "flow.sh").write_text("cga test run\n")
            chain_id = repository.start_chain(name="main")
            with repository.locked():
                manifest = repository.load_manifest()
                _, chain = repository.resolve_chain(manifest, chain_id)
                repository.record_state(
                    manifest,
                    chain_id,
                    chain,
                    {"done": True},
                    ["cga", "test", "run"],
                    "flow",
                )
            model = workflow_model(repository)
            self.assertEqual(model["flow"]["id"], "test")
            self.assertEqual(model["stages"][0]["id"], "custom")
            self.assertEqual(model["links"]["source"], "/existing/source")
            self.assertEqual(flow_source_path(repository), root / "flow.sh")


if __name__ == "__main__":
    unittest.main()
