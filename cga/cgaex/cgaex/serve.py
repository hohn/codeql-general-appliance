"""Live export fragments rendered from the session CGAST."""

from __future__ import annotations

from typing import Any, Dict

import cga_http as C
import cgast

COMPONENT = "cgaex"
EXPORTS_KEY = "cgaex-exports"


def _exports(state: Dict[str, Any]) -> Dict[str, Any]:
    value = state.get(EXPORTS_KEY, {})
    return value if isinstance(value, dict) else {}


def overview_fragment() -> str:
    state = cgast.load_session()
    exports = _exports(state)
    body = C.kv_table([
        ("formats", ", ".join(sorted(exports)) or "(none)"),
        ("findings", str(state.get("cgaex-finding-count", 0))),
        ("active", str(state.get("cgaex-active", "(none)"))),
    ])
    return C.fragment(
        COMPONENT, "cga result export", body,
        tip="cgaex/overview -- human and LLM result exports",
    )


def detail_fragment() -> str:
    state = cgast.load_session()
    exports = _exports(state)
    if not exports:
        body = (
            "<p>No exports yet.</p>"
            "<p>Run <code>cgaex human</code> or <code>cgaex llm</code>.</p>"
        )
    else:
        rows = "".join(
            "<tr>"
            f"<td>{C.esc(name)}</td>"
            f"<td>{C.esc(item.get('path', ''))}</td>"
            f"<td>{C.esc(item.get('finding_count', 0))}</td>"
            "</tr>"
            for name, item in sorted(exports.items())
            if isinstance(item, dict)
        )
        body = (
            '<table class="cga-list"><thead><tr><th>format</th>'
            "<th>path</th><th>findings</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
    return C.fragment(
        COMPONENT, "cga result export -- detail", body,
        tip="cgaex/detail -- generated result artifacts",
    )


def routes() -> Dict[str, Any]:
    return {"/overview": overview_fragment, "/detail": detail_fragment}
