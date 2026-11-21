"""HTTP fragment views for cgaql -- rendered from the session CGAST.

The ``serve`` viewer re-reads the session CGAST (cga-tmp/session.json by default)
on every request, so CLI updates show up live. ``/overview`` summarises the
query catalogue named by ``cgaql-index``; ``/detail`` renders the user-scoped
selection history (``cgaql-history``) and its cached pack bundles.
"""

from __future__ import annotations

from typing import Any, Dict, List

import cga_http as C  # provided on sys.path by bin/cgaql
import cgast

from . import catalog, selection

COMPONENT = "cgaql"


def _groups(
        session: Dict[str, Any],
) -> List[tuple[str, Any, List[Dict[str, Any]], List[str]]]:
    groups = []
    history = session.get("cgaql-history", [])
    if isinstance(history, list):
        for item in history:
            if not isinstance(item, dict) or not item.get("selection"):
                continue
            path = cgast.resolve(item["selection"])
            packs = item.get("packs", [])
            groups.append((str(item.get("user") or "(unknown)"), path,
                           selection.read_selection(path),
                           packs if isinstance(packs, list) else []))
    if not groups:
        path = cgast.get_path(session, "cgaql-selection")
        if path:
            packs = session.get("cgaql-pack", [])
            groups.append(("(unknown)", path, selection.read_selection(path),
                           packs if isinstance(packs, list) else []))
    return groups


def overview_fragment() -> str:
    session = cgast.load_session()
    index = cgast.get_path(session, "cgaql-index")
    sel = cgast.get_path(session, "cgaql-selection")
    if index is None:
        body = C.kv_table([
            ("index", "(none in session)"),
            ("hint", "echo '{}' | cgaql index <dir> > cga-tmp/session.json"),
        ])
        return C.fragment(COMPONENT, "cga query library", body,
                          tip="cgaql/overview -- CodeQL query catalogue")
    try:
        conn = catalog.connect(index)
        try:
            total = catalog.count(conn)
            keys = catalog.keys(conn)
            lang_rows = catalog.run_sql(
                conn,
                "SELECT language, COUNT(*) FROM queries "
                "GROUP BY language ORDER BY COUNT(*) DESC",
            )
            langs = ", ".join(f"{r[0] or '(none)'} ({r[1]})" for r in lang_rows)
        finally:
            conn.close()
        groups = _groups(session)
        selected = sum(len(rows) for _user, _path, rows, _packs in groups)
        n_packs = sum(len(packs) for _user, _path, _rows, packs in groups)
        users = sorted({user for user, _path, _rows, _packs in groups})
        body = C.kv_table([
            ("queries", str(total)),
            ("languages", langs),
            ("keys", ", ".join(keys)),
            ("selections", str(len(groups))),
            ("selected queries", str(selected)),
            ("cached packs", str(n_packs)),
            ("users", ", ".join(users) or "(none)"),
            ("index", cgast.rel(index)),
        ])
    except catalog.CatalogError as exc:
        body = C.kv_table([("index", cgast.rel(index)), ("error", str(exc))])
    return C.fragment(COMPONENT, "cga query library", body,
                      tip="cgaql/overview -- CodeQL query catalogue")


def detail_fragment() -> str:
    session = cgast.load_session()
    groups = _groups(session)
    rows = [(user, row) for user, _path, selected, _packs in groups
            for row in selected]
    packs = [(user, pack_path) for user, _path, _selected, cached in groups
             for pack_path in cached]

    if not rows:
        body = (
            '<p>No queries selected yet.</p>'
            '<p>Write a selection with '
            '<code>cgaql select &lt;key&gt; &lt;value&gt; ...</code>, then '
            '<code>cgaql pack</code>.</p>'
        )
        return C.fragment(COMPONENT, "cga query library -- detail", body,
                          tip="cgaql/detail -- selected queries")

    header = (
        '<tr><th>user</th><th>language</th><th>id</th><th>kind</th>'
        '<th>severity</th><th>relpath</th></tr>'
    )
    trs = "".join(
        '<tr>'
        f'<td>{C.esc(user)}</td>'
        f'<td>{C.esc(r.get("language", ""))}</td>'
        f'<td>{C.esc(r.get("id", ""))}</td>'
        f'<td>{C.esc(r.get("kind", ""))}</td>'
        f'<td>{C.esc(r.get("severity", ""))}</td>'
        f'<td>{C.esc(r.get("relpath", ""))}</td>'
        '</tr>'
        for user, r in rows
    )
    pack_html = ""
    if packs:
        items = "".join(
            f'<li>{C.esc(user)}: <code>{C.esc(p)}</code></li>'
            for user, p in packs)
        pack_html = (f'<p>{len(packs)} pack bundle(s) cached:</p>'
                     f'<ul>{items}</ul>')
    table = (
        f'<p>{len(rows)} query(ies) across {len(groups)} selection(s):</p>'
        f'<table class="cga-list"><thead>{header}</thead>'
        f'<tbody>{trs}</tbody></table>'
        f'{pack_html}'
    )
    return C.fragment(COMPONENT, "cga query library -- detail", table,
                      tip="cgaql/detail -- selected queries")


def routes() -> Dict[str, Any]:
    return {"/overview": overview_fragment, "/detail": detail_fragment}
