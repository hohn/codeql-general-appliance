const state = {
  model: null,
  modelSignature: null,
  selected: null,
  selectionRequest: 0,
  collapsedStages: new Set(),
  workflowQuery: "",
  audience: "",
  collection: null,
};

const SPLIT_STORAGE = {
  workflow: "cgauv.workflowPaneWidth",
  detail: "cgauv.detailPaneHeight",
};
const THEME_STORAGE_KEY = "cga.theme";

function setTheme(theme, persist = true) {
  const value = ["dark", "light", "font-on-white", "minimalist-bw"].includes(theme)
    ? theme
    : "dark";
  document.documentElement.dataset.theme = value;
  document.getElementById("theme-select").value = value;
  if (persist) {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, value);
    } catch (_error) {
      // The visual choice still applies when storage is disabled.
    }
  }
}

function initializeTheme() {
  let stored = "dark";
  try {
    stored = localStorage.getItem(THEME_STORAGE_KEY) || "dark";
  } catch (_error) {
    // Storage can be disabled; the explicit dark default remains usable.
  }
  setTheme(stored, false);
  document.getElementById("theme-select").addEventListener("change", (event) => {
    setTheme(event.target.value);
  });
}

function initializeSystemSummary() {
  const control = document.getElementById("collapse-system");
  const body = document.getElementById("system-body");
  control.addEventListener("click", () => {
    body.hidden = !body.hidden;
    control.textContent = body.hidden ? "\u25b8" : "\u25be";
    control.setAttribute("aria-expanded", String(!body.hidden));
    const label = `${body.hidden ? "expand" : "collapse"} MRVA system summary`;
    control.setAttribute("aria-label", label);
    control.title = label;
  });
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

async function fetchJSON(url) {
  const response = await fetch(url, { cache: "no-store" });
  const value = await response.json();
  if (!response.ok && !value.available) return value;
  if (!response.ok) throw new Error(value.error || `HTTP ${response.status}`);
  return value;
}

function commandTooltip(step) {
  const delta = step.delta || {};
  const parts = [
    step.command_text || "",
    `added: ${(delta.added || []).join(", ") || "-"}`,
    `updated: ${(delta.updated || []).join(", ") || "-"}`,
    `removed: ${(delta.removed || []).join(", ") || "-"}`,
  ];
  if (step.source && step.source.preview) parts.push("", step.source.preview);
  if (step.error) parts.push("", `error: ${step.error}`);
  return parts.join("\n");
}

function updateCollapseAllControl() {
  const groups = Array.from(document.querySelectorAll(".stage"));
  const allCollapsed = groups.length > 0 && groups.every((group) => !group.open);
  const control = document.getElementById("collapse-all");
  control.textContent = allCollapsed ? "\u25b8" : "\u25be";
  control.setAttribute("aria-expanded", String(!allCollapsed));
  control.setAttribute(
    "aria-label",
    allCollapsed
      ? "expand all workflow stages"
      : "collapse all workflow stages",
  );
  control.title = allCollapsed
    ? "expand all workflow stages"
    : "collapse all workflow stages";
}

function renderFlow(model) {
  window.CGAVID?.setContext(model.vid_context);
  const host = document.getElementById("stage-list");
  const scrollTop = host.scrollTop;
  host.replaceChildren();
  let index = 0;
  let total = 0;
  for (const stage of model.stages || []) {
    total += stage.steps.length;
    const visibleSteps = stage.steps.filter((step) => {
      const query = state.workflowQuery.toLowerCase();
      const text = [
        step.label,
        step.command_text,
        step.source?.preview || "",
        ...(step.tags?.canonical || []),
        ...(step.tags?.profiles || []),
      ]
        .join(" ")
        .toLowerCase();
      if (query && !text.includes(query)) return false;
      const audiences = step.tags?.values?.audience || [];
      return !state.audience || audiences.includes(state.audience);
    });
    if (!visibleSteps.length) continue;
    const group = el("details", "stage");
    group.dataset.stageId = stage.id;
    group.open = !state.collapsedStages.has(stage.id);
    group.addEventListener("toggle", () => {
      if (group.open) state.collapsedStages.delete(stage.id);
      else state.collapsedStages.add(stage.id);
      updateCollapseAllControl();
    });
    group.appendChild(el("summary", null, `${stage.label} (${visibleSteps.length})`));
    const steps = el("div", "stage-steps");
    for (const step of visibleSteps) {
      index += 1;
      const button = el(
        "button",
        `step ${step.status === "failed" ? "failed" : ""}`,
      );
      button.type = "button";
      button.dataset.stepId = step.id;
      button.title = commandTooltip(step);
      button.appendChild(el("span", "step-index", String(index).padStart(2, "0")));
      button.appendChild(el("span", "step-label", step.label));
      button.appendChild(el("span", "step-command", step.command_text));
      button.addEventListener("click", () => selectStep(step.id));
      steps.appendChild(button);
      window.CGAVID?.attach(button, step.vid);
    }
    group.appendChild(steps);
    host.appendChild(group);
  }
  document.getElementById("step-count").textContent =
    index === total ? `${total} steps` : `${index}/${total} steps`;
  host.scrollTop = scrollTop;
  updateCollapseAllControl();
}

function renderHeader(model) {
  const chain = model.chain;
  document.getElementById("workflow-meta").textContent = chain
    ? `${model.workflow} · ${chain.name || chain.id} · ${chain.step_count} steps`
    : `${model.workflow} · no active chain`;
  document.getElementById("workflow-state-link").href =
    model.links.workflow_state;
  document.getElementById("sysview-link").href = model.links.mrva_sysview;
  document.getElementById("replay-link").href = model.links.replay;
  document.getElementById("dfg-link").href = model.links.dfg;
  document.getElementById("cfg-link").href = model.links.cfg;
  const sourceLink = document.getElementById("source-link");
  sourceLink.hidden = !model.links.source;
  if (model.links.source) sourceLink.href = model.links.source;
}

function countBy(rows, key) {
  const result = new Map();
  for (const row of rows || []) {
    const value = String(row[key] == null ? "unknown" : row[key]);
    result.set(value, (result.get(value) || 0) + 1);
  }
  return result;
}

function summaryCard(label, value, note) {
  const card = el("div", "summary-card");
  card.appendChild(el("span", null, label));
  card.appendChild(el("strong", null, String(value)));
  if (note) card.appendChild(el("span", null, note));
  return card;
}

function renderSystem(payload) {
  const badge = document.getElementById("system-availability");
  const summary = document.getElementById("system-summary");
  const detail = document.getElementById("system-detail");
  summary.replaceChildren();
  detail.replaceChildren();
  if (!payload.available) {
    badge.className = "badge bad";
    badge.textContent = "unavailable";
    summary.appendChild(summaryCard("MRVA", "offline", payload.error || ""));
    return;
  }
  badge.className = "badge ok";
  badge.textContent = "live";
  const data = payload.data || {};
  const servers = data.servers || [];
  const workers = data.workers || [];
  const jobs = data.jobs || [];
  const spawns = data.spawns || [];
  const identity = state.model?.mrva || {};
  const matchingJobs =
    identity.user != null && identity.session_id != null
      ? jobs.filter(
          (job) =>
            String(job.user) === String(identity.user) &&
            String(job.session_id) === String(identity.session_id),
        )
      : jobs;
  const onlineServers = servers.filter((server) => server.online).length;
  const jobStates = countBy(matchingJobs, "status");
  const workerStates = countBy(workers, "status");
  summary.appendChild(summaryCard("servers online", onlineServers, `${servers.length} known`));
  summary.appendChild(summaryCard("workers", workers.length, `${workerStates.size} states`));
  summary.appendChild(
    summaryCard(
      identity.submission ? `jobs · ${identity.submission}` : "jobs",
      matchingJobs.length,
      `${jobStates.size} states · ${jobs.length} total`,
    ),
  );
  summary.appendChild(summaryCard("pending spawns", spawns.length, ""));
  summary.appendChild(summaryCard("served by", data.served_by || "-", data.generated_at || ""));

  const serverCard = el("div", "relation-card");
  serverCard.appendChild(el("h3", null, "Servers"));
  serverCard.appendChild(
    el(
      "div",
      "kv",
      null,
    ),
  );
  const serverText = servers.length
    ? servers
        .map(
          (server) =>
            `${server.role || "server"}: ${server.instance_id || "unknown"} · ${
              server.online ? "online" : "offline"
            }`,
        )
        .join("\n")
    : "No registered servers.";
  serverCard.appendChild(el("pre", null, serverText));
  detail.appendChild(serverCard);

  const runtimeCard = el("div", "relation-card");
  runtimeCard.appendChild(el("h3", null, "Runtime counts"));
  runtimeCard.appendChild(
    el(
      "pre",
      null,
      `job states: ${JSON.stringify(Object.fromEntries(jobStates))}\n` +
        `worker states: ${JSON.stringify(Object.fromEntries(workerStates))}\n` +
        `pending spawns: ${spawns.length}`,
    ),
  );
  detail.appendChild(runtimeCard);
}

function jsonCard(title, value, wide = false) {
  const card = el("section", `data-card ${wide ? "wide" : ""}`);
  card.appendChild(el("h3", null, title));
  card.appendChild(el("pre", null, JSON.stringify(value, null, 2)));
  return card;
}

function metadataList(detail) {
  const list = el("dl", "kv");
  const values = [
    ["id", detail.id],
    ["command", detail.command_text],
    ["parent", detail.parent || "(root)"],
    ["children", (detail.children || []).join(", ") || "(none)"],
    ["started", detail.execution?.started_at || "(not captured)"],
    ["finished", detail.execution?.finished_at || "(not captured)"],
    ["duration", detail.execution?.duration_seconds ?? "(not captured)"],
    ["exit", detail.execution?.exit_code ?? "(not captured)"],
  ];
  for (const [key, value] of values) {
    list.appendChild(el("dt", null, key));
    list.appendChild(el("dd", null, String(value)));
  }
  return list;
}

function renderDetail(detail) {
  state.selected = detail.id;
  document.querySelectorAll(".step").forEach((step) => {
    step.classList.toggle("selected", step.dataset.stepId === detail.id);
  });
  document.getElementById("detail-title").textContent = detail.label;
  document.getElementById("detail-subtitle").textContent = detail.command_text;
  const badge = document.getElementById("detail-status");
  badge.textContent = detail.status;
  badge.className = `badge ${detail.status === "failed" ? "bad" : "ok"}`;

  const body = document.getElementById("detail-body");
  body.className = "detail-body";
  body.replaceChildren();
  const grid = el("div", "detail-grid");
  const metadata = el("section", "data-card");
  metadata.appendChild(el("h3", null, "Execution"));
  metadata.appendChild(metadataList(detail));
  grid.appendChild(metadata);

  const source = el("section", "data-card");
  source.appendChild(el("h3", null, "Source"));
  const sourceMeta = detail.source || {};
  source.appendChild(
    el(
      "p",
      null,
      sourceMeta.path
        ? `${sourceMeta.path}:${sourceMeta.start_line}-${sourceMeta.end_line}`
        : "Source provenance was not captured for this step.",
    ),
  );
  if (sourceMeta.excerpt) {
    source.appendChild(el("pre", "source-excerpt", sourceMeta.excerpt));
  }
  grid.appendChild(source);
  grid.appendChild(jsonCard("State delta", detail.state_delta, true));
  grid.appendChild(jsonCard("Component state", detail.component_state, true));
  const artifacts = el("section", "data-card wide");
  artifacts.appendChild(el("h3", null, "Artifacts"));
  for (const artifact of detail.artifacts || []) {
    const label = el("span", null, artifact.logical_name || artifact.id);
    artifacts.appendChild(label);
    window.CGAVID?.attach(label, artifact.vid);
    artifacts.appendChild(el("pre", null, JSON.stringify(artifact, null, 2)));
  }
  grid.appendChild(artifacts);
  body.appendChild(grid);

  document.getElementById("terminal-meta").textContent =
    `${detail.command_text} · exit ${detail.execution?.exit_code ?? "unknown"}`;
  document.getElementById("terminal-output").textContent =
    detail.transcript || "(No transcript was captured for this command.)";
}

async function selectStep(stepId) {
  state.collection = null;
  state.selected = stepId;
  const request = ++state.selectionRequest;
  try {
    const detail = await fetchJSON(`api/step?id=${encodeURIComponent(stepId)}`);
    if (request !== state.selectionRequest) return;
    renderDetail(detail);
  } catch (error) {
    if (request !== state.selectionRequest) return;
    document.getElementById("detail-body").textContent = String(error);
  }
}

const COLLECTION_FIELDS = {
    databases: [
      "git_owner",
      "git_repo",
      "primary_language",
      "tool_version",
      "db_file_size",
      "git_commit_id",
    ],
    queries: [
      "id",
      "name",
      "language",
      "kind",
      "severity",
      "relpath",
      "file_size",
    ],
};

function collectionURL(kind, options) {
    const query = new URLSearchParams();
    if (options.query) query.set("q", options.query);
    if (options.filterField && options.filterValue) {
      query.append("filter", `${options.filterField}:${options.filterValue}`);
    }
    if (options.sort) query.set("sort", options.sort);
    query.set("offset", String(options.offset || 0));
    query.set("limit", String(options.limit || 50));
    return `api/collections/${kind}?${query}`;
}

async function showCollection(kind, options = {}) {
    const request = {
      query: options.query || "",
      filterField: options.filterField || "",
      filterValue: options.filterValue || "",
      sort: options.sort || "",
      offset: options.offset || 0,
      limit: options.limit || 50,
    };
    const documentValue = await fetchJSON(collectionURL(kind, request));
    state.collection = { kind, ...request };
    state.selected = null;
    document.querySelectorAll(".step").forEach((step) => {
      step.classList.remove("selected");
    });
    document.getElementById("detail-title").textContent =
      kind === "databases" ? "Selected databases" : "Selected queries";
    document.getElementById("detail-subtitle").textContent =
      `origin: ${documentValue.origin_steps.join(", ") || "(unknown)"}`;
    const badge = document.getElementById("detail-status");
    badge.textContent = `${documentValue.page.total} items`;
    badge.className = "badge";

    const body = document.getElementById("detail-body");
    body.className = "detail-body";
    body.replaceChildren();
    const tools = el("div", "collection-tools");
    const search = el("input");
    search.type = "search";
    search.placeholder = `search selected ${kind}`;
    search.value = request.query;
    search.setAttribute("aria-label", `search selected ${kind}`);
    const field = el("select");
    field.setAttribute("aria-label", "filter field");
    field.appendChild(new Option("filter field", ""));
    for (const name of COLLECTION_FIELDS[kind]) {
      field.appendChild(new Option(name, name));
    }
    field.value = request.filterField;
    const filterValue = el("input");
    filterValue.placeholder = "exact value";
    filterValue.value = request.filterValue;
    filterValue.setAttribute("aria-label", "filter value");
    const sort = el("select");
    sort.setAttribute("aria-label", "sort collection");
    sort.appendChild(new Option("sort", ""));
    for (const name of COLLECTION_FIELDS[kind]) {
      sort.appendChild(new Option(name, name));
    }
    sort.value = request.sort;
    const apply = el("button", null, "apply");
    apply.type = "button";
    const previous = el("button", null, "previous");
    previous.type = "button";
    previous.disabled = documentValue.page.offset === 0;
    const next = el("button", null, "next");
    next.type = "button";
    next.disabled = !documentValue.page.truncated;
    const reload = (offset = 0) =>
      showCollection(kind, {
        query: search.value,
        filterField: field.value,
        filterValue: filterValue.value,
        sort: sort.value,
        offset,
        limit: request.limit,
      });
    apply.addEventListener("click", () => reload(0));
    search.addEventListener("keydown", (event) => {
      if (event.key === "Enter") reload(0);
    });
    previous.addEventListener("click", () =>
      reload(Math.max(0, documentValue.page.offset - request.limit)),
    );
    next.addEventListener("click", () =>
      reload(documentValue.page.offset + request.limit),
    );
    for (const control of [
      search,
      field,
      filterValue,
      sort,
      apply,
      previous,
      next,
    ]) {
      tools.appendChild(control);
    }
    body.appendChild(tools);
    body.appendChild(
      el(
        "p",
        "collection-summary",
        `${documentValue.page.count} shown · ${documentValue.page.total} total` +
          (documentValue.page.truncated ? " · more available" : ""),
      ),
    );
    const wrap = el("div", "collection-table-wrap");
    const table = el("table", "collection-table");
    const head = el("thead");
    const headRow = el("tr");
    for (const name of COLLECTION_FIELDS[kind]) {
      headRow.appendChild(el("th", null, name));
    }
    head.appendChild(headRow);
    table.appendChild(head);
    const bodyRows = el("tbody");
    for (const item of documentValue.items) {
      const row = el("tr");
      for (const name of COLLECTION_FIELDS[kind]) {
        const cell = el("td");
        cell.appendChild(el("span", null, String(item[name] ?? "")));
        row.appendChild(cell);
      }
      bodyRows.appendChild(row);
      window.CGAVID?.attach(row.firstChild?.firstChild, item.vid);
    }
    table.appendChild(bodyRows);
    wrap.appendChild(table);
    body.appendChild(wrap);
    document.getElementById("terminal-meta").textContent =
      `${kind} collection · ${documentValue.page.total} items`;
    document.getElementById("terminal-output").textContent =
      JSON.stringify(documentValue.tags, null, 2);
}

function toggleAllStages() {
  const groups = Array.from(document.querySelectorAll(".stage"));
  const collapse = groups.some((group) => group.open);
  for (const group of groups) {
    group.open = !collapse;
    if (collapse) state.collapsedStages.add(group.dataset.stageId);
    else state.collapsedStages.delete(group.dataset.stageId);
  }
  updateCollapseAllControl();
}

function revealSelectedStep() {
  if (!state.selected) return;
  const selector = `.step[data-step-id="${CSS.escape(state.selected)}"]`;
  const step = document.querySelector(selector);
  if (!step) return;
  const group = step.closest(".stage");
  if (group && !group.open) {
    group.open = true;
    const modelStage = (state.model?.stages || []).find((stage) =>
      stage.steps.some((item) => item.id === state.selected),
    );
    if (modelStage) state.collapsedStages.delete(modelStage.id);
  }
  step.scrollIntoView({ behavior: "smooth", block: "center" });
  step.classList.remove("attention");
  requestAnimationFrame(() => step.classList.add("attention"));
  setTimeout(() => step.classList.remove("attention"), 1200);
  updateCollapseAllControl();
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function updateSeparatorValue(separator, value, minimum, maximum) {
  separator.setAttribute("aria-valuemin", String(Math.round(minimum)));
  separator.setAttribute("aria-valuemax", String(Math.round(maximum)));
  separator.setAttribute("aria-valuenow", String(Math.round(value)));
}

function setWorkflowPaneWidth(value, persist = true) {
  const workspace = document.querySelector(".workspace");
  const separator = document.getElementById("workflow-splitter");
  const width = workspace.getBoundingClientRect().width;
  const maximum = Math.max(260, width - 380);
  const next = clamp(value, 260, maximum);
  workspace.style.setProperty("--flow-pane-width", `${next}px`);
  updateSeparatorValue(separator, next, 260, maximum);
  if (persist) localStorage.setItem(SPLIT_STORAGE.workflow, String(next));
}

function setDetailPaneHeight(value, persist = true) {
  const column = document.querySelector(".right-column");
  const separator = document.getElementById("detail-splitter");
  const height = column.getBoundingClientRect().height;
  const maximum = Math.max(220, height - 190);
  const next = clamp(value, 220, maximum);
  column.style.setProperty("--detail-pane-height", `${next}px`);
  updateSeparatorValue(separator, next, 220, maximum);
  if (persist) localStorage.setItem(SPLIT_STORAGE.detail, String(next));
}

function installSplitter(separator, orientation, setValue, currentValue) {
  let dragging = false;
  const move = (event) => {
    if (!dragging) return;
    const container =
      orientation === "vertical"
        ? document.querySelector(".workspace")
        : document.querySelector(".right-column");
    const bounds = container.getBoundingClientRect();
    setValue(
      orientation === "vertical"
        ? event.clientX - bounds.left
        : event.clientY - bounds.top,
    );
  };
  separator.addEventListener("pointerdown", (event) => {
    dragging = true;
    separator.classList.add("dragging");
    separator.setPointerCapture(event.pointerId);
    event.preventDefault();
  });
  separator.addEventListener("pointermove", move);
  separator.addEventListener("pointerup", (event) => {
    dragging = false;
    separator.classList.remove("dragging");
    separator.releasePointerCapture(event.pointerId);
  });
  separator.addEventListener("pointercancel", () => {
    dragging = false;
    separator.classList.remove("dragging");
  });
  separator.addEventListener("keydown", (event) => {
    const decrease =
      orientation === "vertical" ? event.key === "ArrowLeft" : event.key === "ArrowUp";
    const increase =
      orientation === "vertical"
        ? event.key === "ArrowRight"
        : event.key === "ArrowDown";
    if (!decrease && !increase) return;
    event.preventDefault();
    setValue(currentValue() + (increase ? 24 : -24));
  });
}

function initializeSplitters() {
  const workspace = document.querySelector(".workspace");
  const column = document.querySelector(".right-column");
  const workflowSeparator = document.getElementById("workflow-splitter");
  const detailSeparator = document.getElementById("detail-splitter");
  const storedWorkflow = Number(localStorage.getItem(SPLIT_STORAGE.workflow));
  const storedDetail = Number(localStorage.getItem(SPLIT_STORAGE.detail));
  setWorkflowPaneWidth(
    Number.isFinite(storedWorkflow) && storedWorkflow > 0
      ? storedWorkflow
      : workspace.getBoundingClientRect().width * 0.31,
    false,
  );
  setDetailPaneHeight(
    Number.isFinite(storedDetail) && storedDetail > 0
      ? storedDetail
      : column.getBoundingClientRect().height * 0.6,
    false,
  );
  installSplitter(
    workflowSeparator,
    "vertical",
    setWorkflowPaneWidth,
    () => document.querySelector(".flow-panel").getBoundingClientRect().width,
  );
  installSplitter(
    detailSeparator,
    "horizontal",
    setDetailPaneHeight,
    () => document.querySelector(".detail-panel").getBoundingClientRect().height,
  );
  workflowSeparator.addEventListener("dblclick", () => {
    setWorkflowPaneWidth(workspace.getBoundingClientRect().width * 0.31);
  });
  detailSeparator.addEventListener("dblclick", () => {
    setDetailPaneHeight(column.getBoundingClientRect().height * 0.6);
  });
  window.addEventListener("resize", () => {
    setWorkflowPaneWidth(
      document.querySelector(".flow-panel").getBoundingClientRect().width,
      false,
    );
    setDetailPaneHeight(
      document.querySelector(".detail-panel").getBoundingClientRect().height,
      false,
    );
  });
}

async function refreshModel() {
  try {
    const model = await fetchJSON("api/model");
    const signature = JSON.stringify(model);
    if (signature === state.modelSignature) return;
    const previous = state.selected;
    state.model = model;
    state.modelSignature = signature;
    renderHeader(model);
    renderFlow(model);
    const ids = (model.stages || []).flatMap((stage) =>
      stage.steps.map((step) => step.id),
    );
    if (state.collection) {
      await showCollection(state.collection.kind, state.collection);
      return;
    }
    const selected = previous && ids.includes(previous) ? previous : ids[ids.length - 1];
    if (selected) await selectStep(selected);
  } catch (error) {
    document.getElementById("workflow-meta").textContent =
      `workflow unavailable: ${String(error)}`;
  }
}

async function refreshSystem() {
  try {
    renderSystem(await fetchJSON("api/sysview"));
  } catch (error) {
    renderSystem({ available: false, error: String(error) });
  }
}

document.getElementById("reload").addEventListener("click", async () => {
  await Promise.all([refreshModel(), refreshSystem()]);
});
document.getElementById("workflow-search").addEventListener("input", (event) => {
  state.workflowQuery = event.target.value;
  if (state.model) renderFlow(state.model);
});
document.getElementById("audience-filter").addEventListener("change", (event) => {
  state.audience = event.target.value;
  if (state.model) renderFlow(state.model);
});
document.getElementById("show-databases").addEventListener("click", () => {
  showCollection("databases");
});
document.getElementById("show-queries").addEventListener("click", () => {
  showCollection("queries");
});
document.getElementById("collapse-all").addEventListener("click", (event) => {
  event.stopPropagation();
  toggleAllStages();
});
document.getElementById("detail-heading").addEventListener("click", () => {
  revealSelectedStep();
});
document.getElementById("detail-heading").addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    revealSelectedStep();
  }
});

initializeTheme();
initializeSystemSummary();
initializeSplitters();
refreshModel();
refreshSystem();
setInterval(refreshModel, 3000);
setInterval(refreshSystem, 1500);
