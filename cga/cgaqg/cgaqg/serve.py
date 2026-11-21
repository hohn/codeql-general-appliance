from __future__ import annotations

from typing import Any

import cga_http as C
import cgast
import workflow

COMPONENT = "cgaqg"


def _manifest():
    session = cgast.load_session()
    path = cgast.get_path(session, "cgaqg-materialized")
    if not path:
        return {}
    try:
        return workflow.load_json(path)
    except workflow.WorkflowError:
        return {}


def overview_fragment() -> str:
    doc = _manifest()
    return C.fragment(COMPONENT, "CVE query generation", C.kv_table([
        ("queries", str(doc.get("count", 0))),
        ("query directory", str(doc.get("querydir", "(none)"))),
    ]))


def detail_fragment() -> str:
    queries = _manifest().get("queries", [])
    rows = "".join(
        f"<tr><td>{C.esc(q.get('id'))}</td><td>{C.esc(q.get('name'))}</td>"
        f"<td>{C.esc(q.get('materialized_path'))}</td></tr>" for q in queries)
    body = ("<p>No queries materialized.</p>" if not queries else
            "<table class=\"cga-list\"><thead><tr><th>id</th><th>name</th>"
            f"<th>path</th></tr></thead><tbody>{rows}</tbody></table>")
    return C.fragment(COMPONENT, "CVE query generation -- detail", body)


def routes() -> dict[str, Any]:
    return {"/overview": overview_fragment, "/detail": detail_fragment}
