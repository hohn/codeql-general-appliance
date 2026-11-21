from __future__ import annotations

from typing import Any

import cga_http as C
import cgast
import workflow

COMPONENT = "cgacv"


def _doc(session, key):
    path = cgast.get_path(session, key)
    if not path:
        return None
    try:
        return workflow.load_json(path)
    except workflow.WorkflowError:
        return None


def overview_fragment() -> str:
    session = cgast.load_session()
    spec = _doc(session, "cgacv-spec") or {}
    selected = _doc(session, "cgacv-selection") or {}
    work = _doc(session, "cgacv-work-items") or {}
    body = C.kv_table([
        ("imported CVEs", str(len(spec.get("cves", [])))),
        ("selected CVEs", str(selected.get("count", 0))),
        ("work items", str(work.get("count", 0))),
    ])
    return C.fragment(COMPONENT, "CVE specifications", body)


def detail_fragment() -> str:
    session = cgast.load_session()
    work = (_doc(session, "cgacv-work-items") or {}).get("items", [])
    if not work:
        return C.fragment(COMPONENT, "CVE specifications -- detail",
                          "<p>No expanded work items.</p>")
    rows = "".join(
        f"<tr><td>{C.esc(x.get('cve'))}</td><td>{C.esc(x.get('package'))}</td>"
        f"<td>{C.esc(x.get('variant'))}</td><td>{C.esc(x.get('version'))}</td></tr>"
        for x in work)
    return C.fragment(COMPONENT, "CVE specifications -- detail",
                      "<table class=\"cga-list\"><thead><tr><th>CVE</th>"
                      "<th>package</th><th>variant</th><th>version</th>"
                      f"</tr></thead><tbody>{rows}</tbody></table>")


def routes() -> dict[str, Any]:
    return {"/overview": overview_fragment, "/detail": detail_fragment}
