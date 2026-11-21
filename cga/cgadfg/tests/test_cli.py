from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT.parent / "cgalib"))

from cgadfg import cli  # noqa: E402
from cgadfg.graph import (  # noqa: E402
    Graph,
    GraphError,
    control_dot_graph,
    control_markdown_table,
    control_plain_table,
    control_user_html,
    data_dot_graph,
    data_markdown_table,
    data_plain_table,
    data_user_html,
)


def _manifest(root: Path) -> Path:
    history = root / "run-history"
    (history / "nodes").mkdir(parents=True)
    document = {
        "active_chain": 1,
        "head": "cga_1_mr_status_0",
        "nodes": {
            "cga_0_mx_reset_0": {
                "id": "cga_0_mx_reset_0", "parent": None,
                "chain_id": 0, "sequence": 0,
                "source_step": "02-reset", "command": ["cgamx", "reset"],
                "created_at": "2026-09-22T00:00:00+00:00",
                "snapshot": "nodes/cga_0_mx_reset_0.json",
            },
            "cga_0_mx_build_1": {
                "id": "cga_0_mx_build_1", "parent": "cga_0_mx_reset_0",
                "chain_id": 0, "sequence": 1,
                "source_step": "03-build", "command": ["cgamx", "build"],
                "created_at": "2026-09-22T00:00:01+00:00",
                "snapshot": "nodes/cga_0_mx_build_1.json",
            },
            "cga_1_mr_status_0": {
                "id": "cga_1_mr_status_0", "parent": "cga_0_mx_build_1",
                "chain_id": 1, "sequence": 0,
                "source_step": "30-status",
                "command": ["cgamr", "status", "--name", "bob-1"],
                "created_at": "2026-09-22T00:00:02+00:00",
                "snapshot": "nodes/cga_1_mr_status_0.json",
            },
        },
        "version": 1,
    }
    path = history / "manifest.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    snapshots = {
        "cga_0_mx_reset_0": {"cgamx-state": {"phase": "reset"}},
        "cga_0_mx_build_1": {
            "cgamx-state": {"phase": "build"},
            "cgamx-binaries": ["mrvaserver", "mrvaagent"],
        },
        "cga_1_mr_status_0": {
            "cgamx-state": {"phase": "build"},
            "cgamx-binaries": ["mrvaserver", "mrvaagent"],
            "cgamr-state": {"bob-1": "succeeded"},
        },
    }
    for node_id, snapshot in snapshots.items():
        (history / document["nodes"][node_id]["snapshot"]).write_text(
            json.dumps(snapshot), encoding="utf-8")
    return path


class GraphTest(unittest.TestCase):
    def test_renderers_preserve_chains_and_cross_chain_parent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            graph = Graph.load(_manifest(Path(raw)))
        self.assertEqual(graph.chain_ids, (0, 1))
        self.assertEqual(graph.root(0).id, "cga_0_mx_reset_0")
        self.assertEqual(graph.chain_head(1).id, "cga_1_mr_status_0")
        plain = control_plain_table(graph)
        self.assertEqual(len(plain.splitlines()), 3)
        self.assertIn("cga_0_mx_build_1", plain)
        markdown = control_markdown_table(graph)
        self.assertIn("| Sequence | Node |", markdown)
        dot = control_dot_graph(graph)
        self.assertIn("rankdir=TB", dot)
        self.assertNotIn("rankdir=LR", dot)
        self.assertIn("subgraph cluster_0", dot)
        self.assertIn("subgraph cluster_1", dot)
        self.assertIn('    "cga_0_mx_reset_0";', dot)
        self.assertNotIn('"cga_0_mx_reset_0" [label=', dot)
        self.assertIn(
            '"cga_0_mx_build_1" -> "cga_1_mr_status_0";', dot)

    def test_data_renderers_show_states_deltas_and_command_edges(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            graph = Graph.load(_manifest(Path(raw)))
            plain = data_plain_table(graph)
            markdown = data_markdown_table(graph)
            dot = data_dot_graph(graph)
        self.assertIn("+cgamx-state", plain)
        self.assertIn("+cgamx-binaries ~cgamx-state", plain)
        self.assertIn("| Sequence | State | Parent state | Data delta |", markdown)
        self.assertTrue(dot.startswith("digraph cgast_data"))
        self.assertIn(
            'label="state cga_0:1\\l+cgamx-binaries ~cgamx-state\\l"', dot)
        self.assertNotIn("\\\\l", dot)
        self.assertIn(
            '"cga_0_mx_reset_0" -> "cga_0_mx_build_1" '
            '[label="cgamx build"];', dot)

    def test_unknown_parent_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = _manifest(Path(raw))
            document = json.loads(path.read_text())
            document["nodes"]["cga_0_mx_build_1"]["parent"] = "missing"
            path.write_text(json.dumps(document))
            with self.assertRaisesRegex(GraphError, "unknown parent"):
                Graph.load(path)

    def test_user_html_simplifies_data_and_control_forests(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            graph = Graph.load(_manifest(Path(raw)))
            data_html = data_user_html(graph)
            control_html = control_user_html(graph)
        self.assertTrue(data_html.startswith("<!doctype html>"))
        self.assertEqual(data_html.count('<circle class="state"'), 3)
        self.assertEqual(data_html.count('<rect class="command"'), 2)
        self.assertIn(">Build infrastructure</text>", data_html)
        self.assertIn(">Check analysis status</text>", data_html)
        self.assertIn("state cga_0:1", data_html)
        self.assertIn(
            "Retrieve the current status of the named analysis submission.",
            data_html,
        )
        self.assertIn("Command: cgamr status --name bob-1", data_html)
        self.assertNotIn(">Reset infrastructure</text>", data_html)
        self.assertIn('id="tooltip"', data_html)
        self.assertIn("node.addEventListener('pointerenter'", data_html)
        self.assertEqual(data_html.count("<title>"), 1)
        self.assertNotIn("<title id=", data_html)
        self.assertIn('role="img" aria-label="CGA data flow"', data_html)
        self.assertEqual(control_html.count('<rect class="command"'), 3)
        self.assertIn(">Reset infrastructure</text>", control_html)
        self.assertIn("step: 30-status", control_html)

    def test_user_html_lays_out_branches_as_a_forest(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = _manifest(Path(raw))
            document = json.loads(path.read_text())
            branch_id = "cga_2_dl_getmeta_0"
            document["nodes"][branch_id] = {
                "id": branch_id,
                "parent": "cga_0_mx_reset_0",
                "chain_id": 2,
                "sequence": 0,
                "source_step": "20-getmeta",
                "command": ["cgadl", "getmeta"],
                "created_at": "2026-09-22T00:00:03+00:00",
                "snapshot": f"nodes/{branch_id}.json",
            }
            path.write_text(json.dumps(document), encoding="utf-8")
            (path.parent / "nodes" / f"{branch_id}.json").write_text(
                json.dumps({"cgadl-metadata": "/tmp/catalogue.sql"}),
                encoding="utf-8",
            )
            graph = Graph.load(path)
            rendered = data_user_html(graph)
        self.assertEqual(rendered.count('<circle class="state"'), 4)
        self.assertEqual(rendered.count('<rect class="command"'), 3)
        self.assertIn(">Fetch DB index</text>", rendered)
        self.assertIn('cx="120"', rendered)
        self.assertIn('cx="360"', rendered)


class CliTest(unittest.TestCase):
    def _run(self, arguments: list[str]) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = cli.main(arguments)
        return result, output.getvalue()

    def test_help_uses_public_data_and_control_flow_names(self) -> None:
        for family, prefix in (("dfg", []), ("cfg", ["--control-flow"])):
            for suffix in ([], ["show"], ["info"]):
                with self.subTest(family=family, command=suffix):
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output), \
                            self.assertRaises(SystemExit) as stopped:
                        cli.main([*prefix, *suffix, "--help"])
                    self.assertEqual(stopped.exception.code, 0)
                    help_text = output.getvalue()
                    public_name = " ".join(["cga", family, *suffix])
                    self.assertIn(f"{public_name} - ", help_text)
                    self.assertIn("Description", help_text)
                    self.assertIn("Environment Variables", help_text)
                    self.assertIn("Example", help_text)
                    self.assertNotIn("  --control-flow", help_text)

    def test_default_manifest_uses_mrva_flow_history(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            path = cli._default_manifest()
        self.assertEqual(
            path.name, "manifest.json")
        self.assertEqual(
            path.parent.name, "mrva-flow-history")

    def test_info_uses_history_environment_and_supports_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            manifest = _manifest(Path(raw))
            with mock.patch.dict(
                    os.environ, {"CGA_HISTORY_DIR": str(manifest.parent)}):
                result, output = self._run(["--markdown", "info"])
        self.assertEqual(result, 0)
        self.assertIn("# Whole-CGAST Data-Flow Graph", output)
        self.assertIn("**Immutable states:** 2", output)
        self.assertIn("**Immutable states:** 1", output)

    def test_dot_and_render_share_the_graph_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            manifest = _manifest(Path(raw))
            result, output = self._run([
                "--manifest", str(manifest), "--dot", "show"])
            self.assertEqual(result, 0)
            self.assertTrue(output.startswith("digraph cgast_data"))

            destination = Path(raw) / "graph.pdf"

            def render(command, check):
                self.assertEqual(command[0:2], ["dot", "-Tpdf"])
                self.assertTrue(Path(command[2]).read_text().startswith(
                    "digraph cgast_data"))
                Path(command[4]).write_bytes(b"%PDF-test")
                return mock.Mock(returncode=0)

            with mock.patch.object(cli.subprocess, "run", side_effect=render):
                result, output = self._run([
                    "--manifest", str(manifest),
                    "--render", str(destination), "show"])
            self.assertEqual(result, 0)
            self.assertEqual(output.strip(), str(destination))
            self.assertEqual(destination.read_bytes(), b"%PDF-test")

    def test_control_flow_mode_preserves_command_graph(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            manifest = _manifest(Path(raw))
            result, output = self._run([
                "--manifest", str(manifest), "--control-flow", "--dot", "show"])
        self.assertEqual(result, 0)
        self.assertTrue(output.startswith("digraph cgast {"))
        self.assertIn("Whole-CGAST control flow", output)
        self.assertNotIn("state cga_", output)

    def test_render_user_writes_html_without_graphviz(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            manifest = _manifest(Path(raw))
            destination = Path(raw) / "user.html"
            with mock.patch.object(cli.subprocess, "run") as run:
                result, output = self._run([
                    "--manifest", str(manifest),
                    "--render-user", str(destination), "show"])
            self.assertEqual(result, 0)
            self.assertEqual(output.strip(), str(destination))
            self.assertIn("<title>CGA data flow</title>", destination.read_text())
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()