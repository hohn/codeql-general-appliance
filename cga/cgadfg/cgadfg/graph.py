"""Load and render immutable whole-CGAST state and command graphs."""

from __future__ import annotations

from dataclasses import dataclass
import html
import json
from pathlib import Path
from typing import Any


class GraphError(ValueError):
    """The history manifest does not describe a valid graph."""


@dataclass(frozen=True)
class Node:
    id: str
    parent: str | None
    chain_id: int
    sequence: int
    source_step: str
    command: tuple[str, ...]
    created_at: str
    snapshot: str

    @classmethod
    def from_dict(cls, node_id: str, value: Any) -> "Node":
        if not isinstance(value, dict):
            raise GraphError(f"node {node_id!r} must be a JSON object")
        try:
            command = value["command"]
            if not isinstance(command, list) or not all(
                    isinstance(item, str) for item in command):
                raise TypeError
            return cls(
                id=str(value["id"]),
                parent=value.get("parent"),
                chain_id=int(value["chain_id"]),
                sequence=int(value["sequence"]),
                source_step=str(value["source_step"]),
                command=tuple(command),
                created_at=str(value["created_at"]),
                snapshot=str(value["snapshot"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise GraphError(f"node {node_id!r} has invalid metadata") from error


@dataclass(frozen=True)
class StateDelta:
    added: tuple[str, ...]
    updated: tuple[str, ...]
    removed: tuple[str, ...]

    @property
    def changed(self) -> tuple[str, ...]:
        return self.added + self.updated + self.removed


@dataclass(frozen=True)
class Graph:
    manifest_path: Path
    active_chain: int | None
    head: str | None
    nodes: tuple[Node, ...]

    @classmethod
    def load(cls, path: Path) -> "Graph":
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except OSError as error:
            raise GraphError(f"cannot read manifest {path}: {error}") from error
        except json.JSONDecodeError as error:
            raise GraphError(f"invalid JSON in manifest {path}: {error}") from error
        if not isinstance(document, dict) or not isinstance(
                document.get("nodes"), dict):
            raise GraphError("manifest must contain a 'nodes' JSON object")
        nodes = tuple(sorted(
            (Node.from_dict(node_id, value)
             for node_id, value in document["nodes"].items()),
            key=lambda node: (node.chain_id, node.sequence, node.id),
        ))
        node_ids = {node.id for node in nodes}
        if len(node_ids) != len(nodes):
            raise GraphError("manifest contains duplicate node IDs")
        for node in nodes:
            if node.parent is not None and node.parent not in node_ids:
                raise GraphError(
                    f"node {node.id!r} references unknown parent {node.parent!r}")
        head = document.get("head")
        if head is not None and head not in node_ids:
            raise GraphError(f"manifest references unknown head {head!r}")
        active_chain = document.get("active_chain")
        return cls(
            manifest_path=path.resolve(),
            active_chain=int(active_chain) if active_chain is not None else None,
            head=head,
            nodes=nodes,
        )

    @property
    def chain_ids(self) -> tuple[int, ...]:
        return tuple(sorted({node.chain_id for node in self.nodes}))

    def chain_nodes(self, chain_id: int) -> tuple[Node, ...]:
        return tuple(node for node in self.nodes if node.chain_id == chain_id)

    def root(self, chain_id: int) -> Node | None:
        nodes = self.chain_nodes(chain_id)
        return nodes[0] if nodes else None

    def chain_head(self, chain_id: int) -> Node | None:
        nodes = self.chain_nodes(chain_id)
        return nodes[-1] if nodes else None

    def snapshot(self, node: Node) -> dict[str, Any]:
        path = self.manifest_path.parent / node.snapshot
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except OSError as error:
            raise GraphError(
                f"cannot read snapshot for {node.id!r}: {path}: {error}") from error
        except json.JSONDecodeError as error:
            raise GraphError(
                f"invalid snapshot JSON for {node.id!r}: {path}: {error}") from error
        if not isinstance(document, dict):
            raise GraphError(f"snapshot for {node.id!r} must be a JSON object")
        return document

    def state_delta(self, node: Node) -> StateDelta:
        current = self.snapshot(node)
        parent = {}
        if node.parent is not None:
            parent_node = next(
                candidate for candidate in self.nodes
                if candidate.id == node.parent)
            parent = self.snapshot(parent_node)
        current_keys = set(current)
        parent_keys = set(parent)
        return StateDelta(
            added=tuple(sorted(current_keys - parent_keys)),
            updated=tuple(sorted(
                key for key in current_keys & parent_keys
                if current[key] != parent[key])),
            removed=tuple(sorted(parent_keys - current_keys)),
        )


def control_plain_table(graph: Graph) -> str:
    rows = [[
        str(node.sequence),
        node.id,
        node.parent or "ROOT",
        node.source_step,
        " ".join(node.command),
    ] for node in graph.nodes]
    if not rows:
        return ""
    widths = [max(len(row[index]) for row in rows) for index in range(4)]
    return "\n".join(
        "  ".join(row[index].ljust(widths[index]) for index in range(4))
        + "  " + row[4]
        for row in rows
    ) + "\n"


def control_markdown_table(graph: Graph) -> str:
    lines = [
        "| Sequence | Node | Parent | Source step | Command |",
        "| ---: | --- | --- | --- | --- |",
    ]
    for node in graph.nodes:
        command = " ".join(node.command).replace("|", "\\|")
        lines.append(
            f"| {node.sequence} | `{node.id}` | `{node.parent or 'ROOT'}` | "
            f"`{node.source_step}` | `{command}` |")
    return "\n".join(lines) + "\n"


def _dot_quote(value: str) -> str:
    return json.dumps(value)


def _dot_left_label(*lines: str) -> str:
    quoted = json.dumps("\n".join(lines) + "\n")
    return quoted.replace("\\n", "\\l")


def control_dot_graph(graph: Graph) -> str:
    lines = [
        "digraph cgast {",
        "  graph [rankdir=TB, labelloc=t, label=\"Whole-CGAST control flow\"];",
        "  node [shape=box, fontname=\"monospace\", fontsize=10];",
        "  edge [color=\"#64748b\"];",
    ]
    for chain_id in graph.chain_ids:
        lines.append(f"  subgraph cluster_{chain_id} {{")
        lines.append(f"    label=\"cga_{chain_id}\";")
        for node in graph.chain_nodes(chain_id):
            attributes = []
            if node.id == graph.head:
                attributes.extend(["penwidth=2", "color=\"#0f766e\""])
            suffix = f" [{', '.join(attributes)}]" if attributes else ""
            lines.append(f"    {_dot_quote(node.id)}{suffix};")
        lines.append("  }")
    for node in graph.nodes:
        if node.parent is not None:
            lines.append(
                f"  {_dot_quote(node.parent)} -> {_dot_quote(node.id)};")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _delta_text(delta: StateDelta) -> str:
    parts = []
    if delta.added:
        parts.append("+" + ",".join(delta.added))
    if delta.updated:
        parts.append("~" + ",".join(delta.updated))
    if delta.removed:
        parts.append("-" + ",".join(delta.removed))
    return " ".join(parts) or "-"


def data_plain_table(graph: Graph) -> str:
    rows = [[
        str(node.sequence),
        node.id,
        node.parent or "ROOT",
        _delta_text(graph.state_delta(node)),
        " ".join(node.command),
    ] for node in graph.nodes]
    if not rows:
        return ""
    widths = [max(len(row[index]) for row in rows) for index in range(4)]
    return "\n".join(
        "  ".join(row[index].ljust(widths[index]) for index in range(4))
        + "  " + row[4]
        for row in rows
    ) + "\n"


def data_markdown_table(graph: Graph) -> str:
    lines = [
        "| Sequence | State | Parent state | Data delta | Produced by |",
        "| ---: | --- | --- | --- | --- |",
    ]
    for node in graph.nodes:
        command = " ".join(node.command).replace("|", "\\|")
        delta = _delta_text(graph.state_delta(node)).replace("|", "\\|")
        lines.append(
            f"| {node.sequence} | `{node.id}` | `{node.parent or 'ROOT'}` | "
            f"`{delta}` | `{command}` |")
    return "\n".join(lines) + "\n"


def data_dot_graph(graph: Graph) -> str:
    lines = [
        "digraph cgast_data {",
        "  graph [rankdir=TB, labelloc=t, label=\"Whole-CGAST data flow\"];",
        "  node [shape=box, fontname=\"monospace\", fontsize=10];",
        "  edge [color=\"#64748b\", fontname=\"monospace\", fontsize=9];",
    ]
    for chain_id in graph.chain_ids:
        lines.append(f"  subgraph cluster_{chain_id} {{")
        lines.append(f"    label=\"cga_{chain_id}\";")
        for node in graph.chain_nodes(chain_id):
            delta = _delta_text(graph.state_delta(node))
            label = _dot_left_label(
                f"state cga_{node.chain_id}:{node.sequence}", delta)
            attributes = [f"label={label}"]
            if node.id == graph.head:
                attributes.extend(["penwidth=2", "color=\"#0f766e\""])
            lines.append(
                f"    {_dot_quote(node.id)} [{', '.join(attributes)}];")
        lines.append("  }")
    for node in graph.nodes:
        if node.parent is not None:
            command = " ".join(node.command)
            lines.append(
                f"  {_dot_quote(node.parent)} -> {_dot_quote(node.id)} "
                f"[label={_dot_quote(command)}];")
    lines.append("}")
    return "\n".join(lines) + "\n"


_USER_COMMANDS = {
    ("cgamx", "preflight"): (
        "Check prerequisites",
        "Check tools, ensure PostgreSQL, and free required ports.",
    ),
    ("cgamx", "reset"): (
        "Reset infrastructure",
        "Drop MRVA tables and clear the work directory and logs.",
    ),
    ("cgamx", "build"): (
        "Build infrastructure",
        "Build the MRVA server and agent.",
    ),
    ("cgamx", "start"): (
        "Start services",
        "Start object storage, the database server, and the MRVA server.",
    ),
    ("cgamx", "logs"): (
        "Inspect service logs",
        "Show the server log and scan it for errors.",
    ),
    ("cgamx", "check"): (
        "Check infrastructure",
        "Fail if the service logs contain real errors.",
    ),
    ("cgadl", "getmeta"): (
        "Fetch DB index",
        "Fetch the database-library metadata index from a URL or path.",
    ),
    ("cgadl", "info"): (
        "Inspect DB library",
        "Show high-level database-library information.",
    ),
    ("cgadl", "sql"): (
        "Select databases",
        "Run the saved read-only database query that defines a selection.",
    ),
    ("cgadl", "download"): (
        "Download databases",
        "Download the selected CodeQL databases.",
    ),
    ("cgaql", "index"): (
        "Index query library",
        "Scan a CodeQL query tree into the query index.",
    ),
    ("cgaql", "info"): (
        "Inspect query library",
        "Show high-level query-library information.",
    ),
    ("cgaql", "select"): (
        "Select queries",
        "Select queries by exact catalogue match.",
    ),
    ("cgaql", "pack"): (
        "Build query pack",
        "Bundle every selected query into a pack.",
    ),
    ("cgamr", "submit"): (
        "Submit analysis",
        "Submit selected databases and a query pack for analysis.",
    ),
    ("cgamr", "status"): (
        "Check analysis status",
        "Retrieve the current status of the named analysis submission.",
    ),
    ("cgamr", "download"): (
        "Download results",
        "Download result archives for the named submission.",
    ),
    ("cgamr", "verify"): (
        "Verify downloads",
        "Verify success status and downloaded archive counts.",
    ),
    ("cgasi", "ingest"): (
        "Import analysis results",
        "Ingest one named analysis submission into the findings stores.",
    ),
    ("cgasi", "verify"): (
        "Verify findings",
        "Verify named ingestions and the cumulative findings database.",
    ),
    ("cgasi", "info"): (
        "Inspect findings",
        "Show cumulative findings-store information.",
    ),
    ("cgaex", "human"): (
        "Export human report",
        "Write a human-readable Markdown findings report.",
    ),
    ("cgaex", "llm"): (
        "Export LLM data",
        "Write a structured JSON findings document for LLM use.",
    ),
    ("cgaex", "info"): (
        "Inspect exports",
        "Show the generated result exports.",
    ),
}


def _fallback_command_label(node: Node) -> str:
    if not node.command:
        return "(unknown)"
    executable = Path(node.command[0]).name
    if len(node.command) == 1:
        return executable
    return f"{executable} {node.command[1]}"


def _user_command(node: Node) -> tuple[str, str]:
    if len(node.command) > 1:
        key = (Path(node.command[0]).name, node.command[1])
        if key in _USER_COMMANDS:
            return _USER_COMMANDS[key]
    label = _fallback_command_label(node)
    return label, "Run this CGA operation."


def _command_tooltip(node: Node) -> str:
    _, synopsis = _user_command(node)
    return f"{synopsis}\n\nCommand: {' '.join(node.command)}"


def _forest_positions(graph: Graph) -> tuple[dict[str, float], dict[str, int]]:
    children = {node.id: [] for node in graph.nodes}
    roots = []
    for node in graph.nodes:
        if node.parent is None:
            roots.append(node.id)
        else:
            children[node.parent].append(node.id)

    by_id = {node.id: node for node in graph.nodes}
    for child_ids in children.values():
        child_ids.sort(key=lambda node_id: (
            by_id[node_id].chain_id,
            by_id[node_id].sequence,
            node_id,
        ))
    roots.sort(key=lambda node_id: (
        by_id[node_id].chain_id,
        by_id[node_id].sequence,
        node_id,
    ))

    x_positions: dict[str, float] = {}
    depths: dict[str, int] = {}
    visiting: set[str] = set()
    visited: set[str] = set()
    next_leaf = 0

    def place(node_id: str, depth: int) -> float:
        nonlocal next_leaf
        if node_id in visiting:
            raise GraphError("manifest parent links contain a cycle")
        visiting.add(node_id)
        depths[node_id] = depth
        child_positions = [
            place(child_id, depth + 1)
            for child_id in children[node_id]
        ]
        if child_positions:
            position = (
                child_positions[0] + child_positions[-1]
            ) / 2
        else:
            position = float(next_leaf)
            next_leaf += 1
        x_positions[node_id] = position
        visiting.remove(node_id)
        visited.add(node_id)
        return position

    for root_id in roots:
        place(root_id, 0)
    if len(visited) != len(graph.nodes):
        raise GraphError("manifest parent links do not form a forest")
    return x_positions, depths


def _svg_document(title: str, width: int, height: int, content: list[str]) -> str:
    escaped_title = html.escape(title)
    return "\n".join([
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escaped_title}</title>",
        "<style>",
        ":root { color-scheme: light dark; }",
        "body { margin: 0; font-family: system-ui, sans-serif; "
        "background: Canvas; color: CanvasText; }",
        "main { padding: 1.5rem; }",
        "h1 { margin: 0 0 1rem; font-size: 1.25rem; }",
        ".graph { overflow: auto; padding: 1rem; border: 1px solid #94a3b8; "
        "border-radius: .5rem; background: #fff; }",
        "svg { display: block; margin: 0 auto; }",
        ".edge { stroke: #64748b; stroke-width: 2; }",
        ".state { fill: #fff; stroke: #0f766e; stroke-width: 3; }",
        ".command { fill: #e2e8f0; stroke: #334155; stroke-width: 2; }",
        ".label { fill: #0f172a; font: 14px ui-monospace, monospace; "
        "text-anchor: middle; dominant-baseline: middle; }",
        ".node:focus > .state, .node:hover > .state, "
        ".node:focus > .command, .node:hover > .command { "
        "stroke: #ea580c; stroke-width: 4; }",
        ".tooltip { position: fixed; z-index: 10; display: none; "
        "max-width: min(42rem, calc(100vw - 2rem)); padding: .5rem .65rem; "
        "border: 1px solid #64748b; border-radius: .35rem; "
        "background: #0f172a; color: #f8fafc; "
        "font: 13px/1.35 ui-monospace, monospace; white-space: pre-wrap; "
        "pointer-events: none; box-shadow: 0 4px 14px rgb(0 0 0 / 30%); }",
        "@media (prefers-color-scheme: dark) {",
        "  .graph { background: #0f172a; }",
        "  .state { fill: #0f172a; stroke: #5eead4; }",
        "  .command { fill: #334155; stroke: #cbd5e1; }",
        "  .label { fill: #f8fafc; }",
        "}",
        "</style>",
        "</head>",
        "<body>",
        "<main>",
        f"<h1>{escaped_title}</h1>",
        '<div class="graph">',
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="{escaped_title}">',
        *content,
        "</svg>",
        "</div>",
        '<div id="tooltip" class="tooltip" role="tooltip"></div>',
        "</main>",
        "<script>",
        "const tooltip = document.getElementById('tooltip');",
        "function placeTooltip(x, y) {",
        "  tooltip.style.display = 'block';",
        "  const gap = 12;",
        "  const bounds = tooltip.getBoundingClientRect();",
        "  tooltip.style.left = `${Math.min(x + gap, "
        "window.innerWidth - bounds.width - gap)}px`;",
        "  tooltip.style.top = `${Math.min(y + gap, "
        "window.innerHeight - bounds.height - gap)}px`;",
        "}",
        "function showTooltip(node, x, y) {",
        "  tooltip.textContent = node.dataset.tooltip;",
        "  placeTooltip(x, y);",
        "}",
        "function hideTooltip() { tooltip.style.display = 'none'; }",
        "for (const node of document.querySelectorAll('.node')) {",
        "  node.addEventListener('pointerenter', event => "
        "showTooltip(node, event.clientX, event.clientY));",
        "  node.addEventListener('pointermove', event => "
        "placeTooltip(event.clientX, event.clientY));",
        "  node.addEventListener('pointerleave', hideTooltip);",
        "  node.addEventListener('focus', () => {",
        "    const bounds = node.getBoundingClientRect();",
        "    showTooltip(node, bounds.right, bounds.top);",
        "  });",
        "  node.addEventListener('blur', hideTooltip);",
        "}",
        "</script>",
        "</body>",
        "</html>",
        "",
    ])


def data_user_html(graph: Graph) -> str:
    x_positions, depths = _forest_positions(graph)
    x_spacing = 240
    y_spacing = 150
    margin_x = 120
    margin_y = 60
    state_radius = 12
    command_height = 38
    max_x = max(x_positions.values(), default=0)
    max_depth = max(depths.values(), default=0)
    width = max(320, int(max_x * x_spacing + margin_x * 2))
    height = max(180, max_depth * y_spacing + margin_y * 2)

    state_points = {
        node.id: (
            margin_x + x_positions[node.id] * x_spacing,
            margin_y + depths[node.id] * y_spacing,
        )
        for node in graph.nodes
    }
    command_points = {
        node.id: (
            state_points[node.id][0],
            state_points[node.id][1] - y_spacing / 2,
        )
        for node in graph.nodes
        if node.parent is not None
    }

    content = []
    for node in graph.nodes:
        if node.parent is None:
            continue
        parent_x, parent_y = state_points[node.parent]
        command_x, command_y = command_points[node.id]
        child_x, child_y = state_points[node.id]
        content.extend([
            f'<line class="edge" x1="{parent_x:g}" '
            f'y1="{parent_y + state_radius:g}" x2="{command_x:g}" '
            f'y2="{command_y - command_height / 2:g}"/>',
            f'<line class="edge" x1="{command_x:g}" '
            f'y1="{command_y + command_height / 2:g}" x2="{child_x:g}" '
            f'y2="{child_y - state_radius:g}"/>',
        ])

    for node in graph.nodes:
        x, y = state_points[node.id]
        tooltip = (
            f"state cga_{node.chain_id}:{node.sequence}\n"
            f"{_delta_text(graph.state_delta(node))}"
        )
        content.extend([
            f'<g class="node" tabindex="0" '
            f'aria-label="{html.escape(tooltip, quote=True)}" '
            f'data-tooltip="{html.escape(tooltip, quote=True)}">',
            f'<circle class="state" cx="{x:g}" cy="{y:g}" r="{state_radius}"/>',
            "</g>",
        ])
        if node.parent is None:
            continue
        command_x, command_y = command_points[node.id]
        label, _ = _user_command(node)
        tooltip = _command_tooltip(node)
        command_width = max(120, len(label) * 9 + 28)
        content.extend([
            f'<g class="node" tabindex="0" '
            f'aria-label="{html.escape(tooltip, quote=True)}" '
            f'data-tooltip="{html.escape(tooltip, quote=True)}">',
            f'<rect class="command" x="{command_x - command_width / 2:g}" '
            f'y="{command_y - command_height / 2:g}" '
            f'width="{command_width}" height="{command_height}" rx="5"/>',
            f'<text class="label" x="{command_x:g}" y="{command_y:g}">'
            f"{html.escape(label)}</text>",
            "</g>",
        ])
    return _svg_document("CGA data flow", width, height, content)


def control_user_html(graph: Graph) -> str:
    x_positions, depths = _forest_positions(graph)
    x_spacing = 240
    y_spacing = 110
    margin_x = 140
    margin_y = 60
    command_height = 38
    max_x = max(x_positions.values(), default=0)
    max_depth = max(depths.values(), default=0)
    width = max(360, int(max_x * x_spacing + margin_x * 2))
    height = max(160, max_depth * y_spacing + margin_y * 2)
    points = {
        node.id: (
            margin_x + x_positions[node.id] * x_spacing,
            margin_y + depths[node.id] * y_spacing,
        )
        for node in graph.nodes
    }
    widths = {
        node.id: max(120, len(_user_command(node)[0]) * 9 + 28)
        for node in graph.nodes
    }

    content = []
    for node in graph.nodes:
        if node.parent is None:
            continue
        parent_x, parent_y = points[node.parent]
        child_x, child_y = points[node.id]
        content.append(
            f'<line class="edge" x1="{parent_x:g}" '
            f'y1="{parent_y + command_height / 2:g}" x2="{child_x:g}" '
            f'y2="{child_y - command_height / 2:g}"/>')

    for node in graph.nodes:
        x, y = points[node.id]
        label, synopsis = _user_command(node)
        tooltip = "\n".join([
            synopsis,
            "",
            f"Command: {' '.join(node.command)}",
            "",
            node.id,
            f"step: {node.source_step}",
            f"created: {node.created_at}",
        ])
        content.extend([
            f'<g class="node" tabindex="0" '
            f'aria-label="{html.escape(tooltip, quote=True)}" '
            f'data-tooltip="{html.escape(tooltip, quote=True)}">',
            f'<rect class="command" x="{x - widths[node.id] / 2:g}" '
            f'y="{y - command_height / 2:g}" width="{widths[node.id]}" '
            f'height="{command_height}" rx="5"/>',
            f'<text class="label" x="{x:g}" y="{y:g}">'
            f"{html.escape(label)}</text>",
            "</g>",
        ])
    return _svg_document("CGA control flow", width, height, content)


# Backward-compatible imports for callers that used the original command graph.
plain_table = control_plain_table
markdown_table = control_markdown_table
dot_graph = control_dot_graph