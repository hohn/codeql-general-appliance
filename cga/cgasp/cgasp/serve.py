from __future__ import annotations

from typing import Any

import cga_http as C
import cgast
import workflow

COMPONENT = "cgasp"


def _sources():
    session = cgast.load_session()
    path = cgast.get_path(session, "cgasp-sources")
    if not path:
        return []
    try:
        return workflow.load_json(path).get("items", [])
    except workflow.WorkflowError:
        return []


def overview_fragment() -> str:
    items = _sources()
    counts = {status: sum(x.get("status") == status for x in items)
              for status in ("ready", "planned", "error")}
    return C.fragment(COMPONENT, "source packages", C.kv_table([
        ("items", str(len(items))), ("ready", str(counts["ready"])),
        ("planned", str(counts["planned"])), ("errors", str(counts["error"])),
    ]))


def detail_fragment() -> str:
    items = _sources()
    rows = "".join(
        f"<tr><td>{C.esc(x.get('id'))}</td><td>{C.esc(x.get('status'))}</td>"
        f"<td>{C.esc(x.get('source_dir'))}</td></tr>" for x in items)
    body = ("<p>No sources fetched.</p>" if not items else
            "<table class=\"cga-list\"><thead><tr><th>item</th><th>status</th>"
            f"<th>source dir</th></tr></thead><tbody>{rows}</tbody></table>")
    return C.fragment(COMPONENT, "source packages -- detail", body)


def routes() -> dict[str, Any]:
    return {"/overview": overview_fragment, "/detail": detail_fragment}
