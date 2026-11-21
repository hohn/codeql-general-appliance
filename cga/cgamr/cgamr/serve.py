"""Live cgamr fragments rendered from the session CGAST."""

from __future__ import annotations

from typing import Any, Dict

import cga_http as C
import cgast

COMPONENT = "cgamr"
STATES = ["idle", "submitting", "status-checking", "downloading", "done"]
STATE_KEY = "cgamr-state"
SESSION_KEY = "cgamr-session"
NOTE_KEY = "cgamr-note"


def state_of(state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "state": state.get(STATE_KEY, "idle"),
        "session": state.get(SESSION_KEY),
        "note": state.get(NOTE_KEY, "no run yet"),
        "active": state.get("cgamr-active"),
    }


def _submissions(state: Dict[str, Any]) -> Dict[str, Any]:
    value = state.get("cgamr-submissions", {})
    return value if isinstance(value, dict) else {}


def _badges(current: str) -> str:
    cells = []
    for stage in STATES:
        cls = "cga-state on" if stage == current else "cga-state"
        cells.append(f'<span class="{cls}" title="{C.esc(stage)}">'
                     f'{C.esc(stage)}</span>')
    return f'<div class="cga-statind">{"".join(cells)}</div>'


def _rows(items: Dict[str, Any]) -> str:
    rows = []
    for name, item in items.items():
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{C.esc(name)}</td>"
            f"<td>{C.esc(item.get('user'))}</td>"
            f"<td>{C.esc(item.get('session_id'))}</td>"
            f"<td>{C.esc(item.get('status'))}</td>"
            f"<td>{len(item.get('repositories', []))}</td>"
            f"<td>{len(item.get('downloads', []))}</td>"
            "</tr>")
    return "".join(rows) or '<tr><td colspan="6">no submissions</td></tr>'


def overview_fragment() -> str:
    state = cgast.load_session()
    current = state_of(state)
    items = _submissions(state)
    body = _badges(current["state"]) + C.kv_table([
        ("active", str(current["active"] or "(none)")),
        ("status", current["state"]),
        ("session", str(current["session"] or "(none)")),
        ("submissions", str(len(items))),
        ("note", current["note"]),
    ])
    return C.fragment(COMPONENT, "cga mrva requestor", body,
                      tip="cgamr/overview -- live submit/status/download state")


def detail_fragment() -> str:
    state = cgast.load_session()
    current = state_of(state)
    items = _submissions(state)
    table = (
        '<p><strong>submission</strong> is the caller-defined run label; '
        '<strong>user</strong> is the MRVA authenticated identity.</p>'
        '<table class="cga-list"><thead><tr>'
        '<th>submission</th><th>user</th><th>session</th><th>status</th>'
        '<th>repos</th><th>archives</th></tr></thead><tbody>'
        f'{_rows(items)}</tbody></table>')
    body = C.kv_table([
        ("active submission", str(current["active"] or "(none)")),
        ("lifecycle stage", current["state"]),
        ("note", current["note"]),
    ]) + table
    return C.fragment(COMPONENT, "cga mrva requestor -- detail", body,
                      tip="cgamr/detail -- named MRVA submissions")


def routes() -> Dict[str, Any]:
    return {"/overview": overview_fragment, "/detail": detail_fragment}
