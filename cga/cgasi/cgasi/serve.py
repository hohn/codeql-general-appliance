"""Live cgasi fragments backed by the cumulative DuckDB in the CGAST."""

from __future__ import annotations

from typing import Any, Dict

import cga_http as C
import cgast

from . import store

COMPONENT = "cgasi"
DB_KEY = "cgasi-db"
INGESTIONS_KEY = "cgasi-ingestions"
VIEW_KEY = "cgasi-view"

# Display label -> the Findings column value read from each result row.
FINDING_CELL = {
    "user": "user",
    "rule": "rule_id",
    "kind": "kind",
    "uri": "uri",
    "line": "start_line",
}


def _state() -> tuple[Dict[str, Any], Any, Dict[str, Any]]:
    session = cgast.load_session()
    db = cgast.get_path(session, DB_KEY)
    ingestions = session.get(INGESTIONS_KEY, {})
    return session, db, ingestions if isinstance(ingestions, dict) else {}


def overview_fragment() -> str:
    _session, db, ingestions = _state()
    rows = 0
    users = sorted({
        str(item.get("user"))
        for item in ingestions.values()
        if isinstance(item, dict) and item.get("user")
    })
    error = ""
    if db:
        try:
            rows = store.count(db)
        except store.StoreError as exc:
            error = str(exc)
    body = C.kv_table([
        ("cumulative db", cgast.rel(db) if db else "(none)"),
        ("ingestions", str(len(ingestions))),
        ("results", str(rows)),
        ("users", ", ".join(users) or "(none)"),
        ("status", error or "ready" if db else "not ingested"),
    ])
    return C.fragment(COMPONENT, "cga sarif ingest", body,
                      tip="cgasi/overview -- cumulative SARIF result store")


def _view(session: Dict[str, Any]) -> tuple[int, Dict[str, str]]:
    view = session.get(VIEW_KEY, {})
    if not isinstance(view, dict):
        view = {}
    erc = view.get("erc", store.DEFAULT_ERC)
    try:
        erc = int(erc)
    except (TypeError, ValueError):
        erc = store.DEFAULT_ERC
    if erc < 0:
        erc = store.DEFAULT_ERC
    raw = view.get("filters", {})
    if not isinstance(raw, dict):
        raw = {}
    filters = {label: str(raw.get(label, "") or "")
               for label in store.FILTER_ORDER}
    return erc, filters


def _erc_chooser(erc: int) -> str:
    options = "".join(
        f'<option value="{choice}"{" selected" if choice == erc else ""}>'
        f'{choice}</option>'
        for choice in store.ERC_CHOICES
    )
    return (
        '<div class="cga-erc-row">'
        '<span>rows:</span> '
        f'<select class="cga-erc-select" data-view-field="erc">{options}</select>'
        ' <button type="button" class="cga-apply" data-comp="cgasi">'
        'apply</button>'
        '</div>'
    )


def _filter_row(filters: Dict[str, str]) -> str:
    cells = "".join(
        '<td><input class="cga-filter" data-view-filter="' + label + '" '
        f'value="{C.esc(filters[label])}" placeholder="(all)" '
        f'title="regex filter for {label}; applied via cgamx cmd (cgasi view '
        f'--{label})"></td>'
        for label in store.FILTER_ORDER
    )
    return f'<tr class="cga-filter-row">{cells}</tr>'


def _findings_table(db: Any, erc: int, filters: Dict[str, str]) -> str:
    header = "".join(f"<th>{label}</th>" for label in store.FILTER_ORDER)
    thead = (f'<thead><tr>{header}</tr>{_filter_row(filters)}</thead>')
    if not db:
        return ('<h3>Findings</h3>'
                '<p>No cumulative database yet. Run an ingestion first.</p>')
    try:
        rows = store.find(db, filters, erc)
    except store.StoreError as exc:
        return ('<h3>Findings</h3>' + _erc_chooser(erc)
                + f'<p>Could not read findings: {C.esc(exc)}</p>')
    if rows:
        body = "".join(
            "<tr>" + "".join(
                f"<td>{C.esc(row.get(FINDING_CELL[label]))}</td>"
                for label in store.FILTER_ORDER) + "</tr>"
            for row in rows
        )
    else:
        any_filter = any(filters[label] for label in store.FILTER_ORDER)
        total = 0
        try:
            total = store.count(db)
        except store.StoreError:
            total = 0
        if any_filter and total:
            message = "No findings match the current filters."
        else:
            message = ("No problem or path-problem findings were present in "
                       "these SARIF inputs. The ingestions above still "
                       "completed successfully.")
        body = f'<tr><td colspan="{len(store.FILTER_ORDER)}">{message}</td></tr>'
    return (
        '<h3>Findings</h3>' + _erc_chooser(erc)
        + '<div class="cga-scroll">'
        + '<table class="cga-list">' + thead
        + f'<tbody>{body}</tbody></table>'
        + '</div>'
    )


def detail_fragment() -> str:
    _session, db, ingestions = _state()
    summary_rows = []
    for name, item in ingestions.items():
        if not isinstance(item, dict):
            continue
        summary_rows.append(
            "<tr>"
            f"<td>{C.esc(name)}</td>"
            f"<td>{C.esc(item.get('user'))}</td>"
            f"<td>{C.esc(item.get('session_id'))}</td>"
            f"<td>{len(item.get('jobs', []))}</td>"
            f"<td>{C.esc(item.get('finding_count', 0))}</td>"
            "</tr>")
    summary = (
        '<h3>Ingestions</h3>'
        '<table class="cga-list"><thead><tr>'
        '<th>name</th><th>user</th><th>session</th><th>inputs</th>'
        '<th>results</th></tr></thead><tbody>'
        + ("".join(summary_rows)
           or '<tr><td colspan="5">no ingestions</td></tr>')
        + "</tbody></table>"
    )

    erc, filters = _view(_session)
    result_table = _findings_table(db, erc, filters)
    return C.fragment(COMPONENT, "cga sarif ingest -- detail",
                      summary + result_table,
                      tip="cgasi/detail -- ingestions and cumulative results")


def routes() -> Dict[str, Any]:
    return {"/overview": overview_fragment, "/detail": detail_fragment}
