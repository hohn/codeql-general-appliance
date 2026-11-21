"use strict";
(() => {
  const element = (id) => document.getElementById(id),
    parameters = new URLSearchParams(location.search),
    session = Number(parameters.get("session")),
    stage = parameters.get("stage"),
    titles = { D: "Databases", Q: "Queries", R: "Result summary", F: "Findings" },
    findings = stage === "F",
    findingsSQL = "SELECT rule_id, uri, start_line, json_extract_string(result_json, '$.message.text') AS message FROM sarif_results ORDER BY rule_id, uri, start_line";
  let offset = 0, page, query, defaultSQL, loading = false,
    mode = "search", filters = {}, editorOpening = false, findingsReady = false;

  async function request(path, document) {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CGA-Bench": "1" },
      body: JSON.stringify(document),
    });
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || response.statusText);
    return value;
  }
  function controls() {
    document.querySelectorAll("button").forEach(button => button.disabled = loading);
    element("evidence-previous").disabled = loading || !page || page.offset === 0;
    element("evidence-next").disabled = loading || !page?.has_more;
    if (findings) element("open-editor").disabled = loading || editorOpening || !findingsReady;
  }
  async function load() {
    loading = true;
    page = undefined;
    element("evidence-head").replaceChildren();
    element("evidence-rows").replaceChildren();
    element("evidence-error").textContent = "";
    element("evidence-status").textContent = "Loading session evidence...";
    controls();
    try {
      const value = await request(findings ? "api/results" : "api/evidence", {
        session, offset, limit: 30,
        ...(findings
          ? mode === "sql" ? { sql: query } : { filters }
          : { stage, ...(query === undefined ? {} : { sql: query }) }),
      });
      page = value;
      defaultSQL = findings ? findingsSQL : value.default_sql;
      if (query === undefined) {
        query = defaultSQL;
        element("evidence-sql").elements.sql.value = query;
      }
      element("evidence-schema").textContent =
        findings
          ? `Table: sarif_results (user, file_name, kind, rule_id, rule_name, uri, start_line, start_column, result_json). ${value.finding_count} findings.`
          : `Table: ${value.table} (${value.source_columns.join(", ")}). ${value.item_count} retained rows; stage ${value.status}.`;
      if (findings) {
        findingsReady = true;
        const repositories = element("result-filters").elements.file_name;
        repositories.replaceChildren(new Option("All repositories", ""));
        for (const repository of value.repositories)
          repositories.append(new Option(
            `${repository.repository} (${repository.finding_count})`, repository.file_name));
        repositories.value = filters.file_name || "";
      }
      const labels = findings ? {
        repository: "Repository", rule_id: "Rule ID", rule_name: "Rule name",
        kind: "Kind", uri: "File URI", start_line: "Line",
        start_column: "Column", message: "Message",
      } : {};
      const header = document.createElement("tr");
      for (const column of value.columns) {
        const th = document.createElement("th");
        th.scope = "col";
        th.textContent = labels[column] || column;
        header.append(th);
      }
      element("evidence-head").append(header);
      for (const row of value.rows) {
        const tr = document.createElement("tr");
        for (const column of value.columns) {
          const td = document.createElement("td"), entry = row[column];
          td.textContent = entry == null ? "" : typeof entry === "object" ? JSON.stringify(entry) : String(entry);
          tr.append(td);
        }
        element("evidence-rows").append(tr);
      }
      const first = value.rows.length ? value.offset + 1 : 0;
      element("evidence-status").textContent =
        (findings ? `${value.mode === "sql" ? "SQL" : "Exact-match search"}: ` : "") +
        `${first}-${value.offset + value.rows.length} of ${value.total} rows.` +
        (!value.rows.length ? " No rows match this view." : "");
    } catch (error) {
      element("evidence-error").textContent = error.message;
      element("evidence-status").textContent = findings
        ? "Findings query failed. Adjust the filters or SQL and retry."
        : "Evidence query failed. Adjust the SQL and retry.";
    } finally {
      loading = false;
      controls();
    }
  }
  element("evidence-sql").addEventListener("submit", (event) => {
    event.preventDefault();
    if (loading) return;
    query = event.target.elements.sql.value;
    mode = "sql";
    offset = 0;
    load();
  });
  function reset() {
    query = defaultSQL;
    element("evidence-sql").elements.sql.value = defaultSQL || "";
    mode = "search";
    filters = {};
    element("result-filters").reset();
    offset = 0;
    load();
  }
  element("evidence-reset").addEventListener("click", reset);
  element("clear-result-filters").addEventListener("click", reset);
  element("result-filters").addEventListener("submit", (event) => {
    event.preventDefault();
    if (loading) return;
    mode = "search";
    filters = Object.fromEntries(
      [...new FormData(event.target)].filter(([, value]) => value !== ""));
    offset = 0;
    load();
  });
  element("evidence-previous").addEventListener("click", () => {
    offset = Math.max(0, offset - 30);
    load();
  });
  element("evidence-next").addEventListener("click", () => {
    offset += 30;
    load();
  });
  element("open-editor").addEventListener("click", async () => {
    if (loading || editorOpening || !findings || !findingsReady) return;
    const popup = window.open("", "_blank", "popup,width=1200,height=850");
    if (!popup) {
      element("editor-status").textContent =
        "Allow pop-ups for this Bench page, then click Open VS Code again.";
      return;
    }
    editorOpening = true;
    element("editor-status").textContent = "Starting VS Code...";
    controls();
    try {
      const descriptor = await request("api/editor", { session });
      if (popup.closed) throw new Error("The VS Code pop-up was closed. Open it again.");
      // Submit locally without putting the generated password in a URL.
      const form = document.createElement("form"),
        password = document.createElement("input");
      form.method = "POST";
      form.action = descriptor.login;
      password.type = "hidden";
      password.name = "password";
      password.value = descriptor.password;
      form.append(password);
      popup.document.body.replaceChildren(form);
      popup.opener = null;
      form.submit();
      popup.focus();
      element("editor-status").textContent = `VS Code: ${descriptor.directory}`;
    } catch (error) {
      element("editor-status").textContent = error.message;
      if (!popup.closed) popup.close();
    } finally {
      editorOpening = false;
      controls();
    }
  });
  if (!Number.isInteger(session) || session < 1 || !Object.hasOwn(titles, stage)) {
    element("evidence-error").textContent = "Select an existing session and evidence stage D, Q, R, or F.";
    document.querySelectorAll("button").forEach(button => button.disabled = true);
    return;
  }
  element("evidence-title").textContent = `Session ${session}: ${titles[stage]}`;
  element("findings-controls").hidden = !findings;
  element("findings-editor").hidden = !findings;
  document.title = `${titles[stage]} | Session ${session} | CGA Bench`;
  load();
})();
