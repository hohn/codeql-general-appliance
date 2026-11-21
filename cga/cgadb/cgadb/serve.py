from __future__ import annotations

from typing import Any

import cga_http as C
import cgast
import workflow

COMPONENT = "cgadb"


def _builds():
    session = cgast.load_session()
    path = cgast.get_path(session, "cgadb-records")
    if not path:
        return []
    try:
        return workflow.load_json(path).get("items", [])
    except workflow.WorkflowError:
        return []


def overview_fragment() -> str:
    items = _builds()
    built = sum(x.get("status") in ("built", "fixture") for x in items)
    errors = sum(x.get("status") == "error" for x in items)
    return C.fragment(COMPONENT, "CodeQL database builds", C.kv_table([
        ("items", str(len(items))), ("archives", str(built)),
        ("errors", str(errors)),
    ]))


def detail_fragment() -> str:
    items = _builds()
    rows = "".join(
        f"<tr><td>{C.esc(x.get('id'))}</td><td>{C.esc(x.get('status'))}</td>"
        f"<td>{C.esc(x.get('archive'))}</td></tr>" for x in items)
    body = ("<p>No builds recorded.</p>" if not items else
            "<table class=\"cga-list\"><thead><tr><th>item</th><th>status</th>"
            f"<th>archive</th></tr></thead><tbody>{rows}</tbody></table>")
    return C.fragment(COMPONENT, "CodeQL database builds -- detail", body)


def routes() -> dict[str, Any]:
    return {"/overview": overview_fragment, "/detail": detail_fragment}
