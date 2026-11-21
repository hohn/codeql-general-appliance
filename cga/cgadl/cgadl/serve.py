"""HTTP fragment views for cgadl -- rendered from the session CGAST.

The ``serve`` viewer re-reads the session CGAST (cga-tmp/session.json by default)
on every request, so CLI updates show up live. ``/overview`` summarises the
catalogue named by ``cgadl-metadata`` and the current selection; ``/detail``
renders the user-scoped selection history (``cgadl-history``).
"""

from __future__ import annotations

from typing import Any, Dict, List

import cga_http as C  # provided on sys.path by bin/cgadl
import cgast

from . import catalog, selection

COMPONENT = "cgadl"


def _groups(
        session: Dict[str, Any],
) -> List[tuple[str, Any, List[Dict[str, Any]]]]:
    groups = []
    history = session.get("cgadl-history", [])
    if isinstance(history, list):
        for item in history:
            if not isinstance(item, dict) or not item.get("selection"):
                continue
            path = cgast.resolve(item["selection"])
            groups.append((str(item.get("user") or "(unknown)"), path,
                           selection.read_selection(path)))
    if not groups:
        path = cgast.get_path(session, "cgadl-selection")
        if path:
            groups.append(("(unknown)", path, selection.read_selection(path)))
    return groups


def _size_mb(value: Any) -> str:
    try:
        return f"{int(value) / (1024 * 1024):.1f}"
    except (TypeError, ValueError):
        return "?"


def overview_fragment() -> str:
    session = cgast.load_session()
    meta = cgast.get_path(session, "cgadl-metadata")
    sel = cgast.get_path(session, "cgadl-selection")
    if meta is None:
        body = C.kv_table([
            ("catalogue", "(none in session)"),
            ("hint", "echo '{}' | cgadl getmeta <url> > cga-tmp/session.json"),
        ])
        return C.fragment(COMPONENT, "cga DB library", body,
                          tip="cgadl/overview -- CodeQL DB catalogue")
    try:
        conn = catalog.connect(meta)
        try:
            total = catalog.count(conn)
            keys = catalog.keys(conn)
            langs_rows = catalog.run_sql(
                conn,
                "SELECT primary_language, COUNT(*) FROM metadata "
                "GROUP BY primary_language ORDER BY COUNT(*) DESC",
            )
            langs = ", ".join(f"{r[0]} ({r[1]})" for r in langs_rows)
        finally:
            conn.close()
        groups = _groups(session)
        selected = sum(len(rows) for _user, _path, rows in groups)
        users = sorted({user for user, _path, _rows in groups})
        body = C.kv_table([
            ("databases", str(total)),
            ("languages", langs),
            ("keys", ", ".join(keys)),
            ("selections", str(len(groups))),
            ("selected databases", str(selected)),
            ("users", ", ".join(users) or "(none)"),
            ("catalogue", cgast.rel(meta)),
        ])
    except catalog.CatalogError as exc:
        body = C.kv_table([("catalogue", cgast.rel(meta)),
                           ("error", str(exc))])
    return C.fragment(COMPONENT, "cga DB library", body,
                      tip="cgadl/overview -- CodeQL DB catalogue")


def detail_fragment() -> str:
    session = cgast.load_session()
    groups = _groups(session)
    rows = [(user, row) for user, _path, selected in groups for row in selected]

    if not rows:
        body = (
            '<p>No databases selected yet.</p>'
            '<p>Write a selection with '
            '<code>cgadl select &lt;key&gt; &lt;value&gt; ...</code>, then '
            '<code>cgadl download</code>.</p>'
        )
        return C.fragment(COMPONENT, "cga DB library -- detail", body,
                          tip="cgadl/detail -- selected databases")

    header = (
        '<tr><th>user</th><th>owner</th><th>repo</th><th>language</th>'
        '<th>tool version</th><th>size (MB)</th><th>result URL</th></tr>'
    )
    trs = "".join(
        '<tr>'
        f'<td>{C.esc(user)}</td>'
        f'<td>{C.esc(r.get("git_owner", ""))}</td>'
        f'<td>{C.esc(r.get("git_repo", ""))}</td>'
        f'<td>{C.esc(r.get("primary_language", ""))}</td>'
        f'<td>{C.esc(r.get("tool_version", ""))}</td>'
        f'<td>{C.esc(_size_mb(r.get("db_file_size")))}</td>'
        f'<td>{C.esc(r.get("result_url", ""))}</td>'
        '</tr>'
        for user, r in rows
    )
    table = (
        f'<p>{len(rows)} database(s) across {len(groups)} selection(s):</p>'
        f'<table class="cga-list"><thead>{header}</thead>'
        f'<tbody>{trs}</tbody></table>'
    )
    return C.fragment(COMPONENT, "cga DB library -- detail", table,
                      tip="cgadl/detail -- selected databases")


def routes() -> Dict[str, Any]:
    return {"/overview": overview_fragment, "/detail": detail_fragment}
