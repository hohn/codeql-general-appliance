"use strict";
let data,
  selected,
  page,
  catalogues,
  busy = false,
  scanning = false,
  offset = 0,
  selectionRequest = 0;
const chosen = new Set(),
  picked = new Set(),
  sources = new Map();
let pickerKey = "",
  editorKey = "",
  detailKey = "";
let resultPage,
  resultRequest = 0,
  resultLoading = false;
let detailView = "infrastructure",
  sessionTab = "D",
  infrastructureDetailPhase,
  infrastructureRun,
  systemSnapshot,
  systemRequest = 0,
  systemFrameError = "",
  presentation;
const evidencePopups = new Map();
const $ = (id) => document.getElementById(id);
const modeButtons = [...document.querySelectorAll("[data-mode]")];
function node(tag, text) {
  const value = document.createElement(tag);
  if (text !== undefined) value.textContent = text;
  return value;
}
function fields(form) {
  return Object.fromEntries(new FormData(form));
}
function inputSource() {
  return selected?.stage === "D" ? "list" : $("input-source").value;
}
function initializeDisclosure(id, bodyId, label) {
  const control = $(id),
    body = $(bodyId);
  control.addEventListener("click", () => {
    body.hidden = !body.hidden;
    control.textContent = body.hidden ? "\u25b8" : "\u25be";
    control.setAttribute("aria-expanded", String(!body.hidden));
    const description = `${body.hidden ? "expand" : "collapse"} ${label}`;
    control.setAttribute("aria-label", description);
    control.title = description;
  });
}
function initializeSplitter() {
  const workspace = document.querySelector(".bench-workspace"),
    splitter = $("workflow-splitter");
  let dragging = false,
    width = presentation.isApple() ? 22 : 36;
  const widths = { apple: 22, classic: 36 };
  function setWidth(value) {
    const total = workspace.clientWidth,
      apple = presentation.isApple(),
      minimum = Math.max(15, ((apple ? 200 : 320) / total) * 100),
      maximum = Math.max(minimum, Math.min(apple ? 45 : 65, ((total - 340) / total) * 100));
    width = Math.min(maximum, Math.max(minimum, value));
    widths[apple ? "apple" : "classic"] = width;
    (apple ? document.body : workspace).style.setProperty(
      apple ? "--outline-pane-width" : "--workflow-pane-width", `${width}%`,
    );
    splitter.setAttribute("aria-valuemin", String(Math.round(minimum)));
    splitter.setAttribute("aria-valuemax", String(Math.round(maximum)));
    splitter.setAttribute("aria-valuenow", String(Math.round(width)));
  }
  setWidth(width);
  splitter.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    splitter.setPointerCapture(event.pointerId);
    dragging = true;
    splitter.classList.add("dragging");
  });
  splitter.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    const box = workspace.getBoundingClientRect();
    setWidth(((event.clientX - box.left) / box.width) * 100);
  });
  function stopDragging() {
    dragging = false;
    splitter.classList.remove("dragging");
  }
  splitter.addEventListener("pointerup", stopDragging);
  splitter.addEventListener("pointercancel", stopDragging);
  splitter.addEventListener("lostpointercapture", stopDragging);
  splitter.addEventListener("dblclick", () => setWidth(presentation.isApple() ? 22 : 36));
  splitter.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home"].includes(event.key)) return;
    event.preventDefault();
    setWidth(
      event.key === "Home" ? (presentation.isApple() ? 22 : 36) : width + (event.key === "ArrowLeft" ? -2 : 2),
    );
  });
  window.addEventListener("resize", () => setWidth(width));
  window.addEventListener("bench-presentation-change", () =>
    setWidth(widths[presentation.isApple() ? "apple" : "classic"]),
  );
}
function initializePresentation() {
  const workspace = document.querySelector(".bench-workspace"),
    outline = $("bench-outline"),
    panels = [
      document.querySelector(".system-panel"),
      $("infrastructure-card"), $("sessions-card"), $("comparison-card"),
    ],
    homes = panels.map((panel) => {
      const marker = document.createComment("classic panel location");
      panel.before(marker);
      return marker;
    }),
    commands = [...$("infrastructure-body").querySelectorAll("button:not(.cga-vid)")],
    buttons = [...document.querySelectorAll("[data-presentation]")],
    disclosureState = new Map(),
    references = new Map();
  let theme, topic = "sessions", currentKey = "sessions", selectedCommand, hasDetail = false,
    outlineCollapsed = false;

  function item(label, key, children, ref, command) {
    const li = node("li"), row = node("div"), select = node("button", label);
    row.className = "outline-row";
    select.type = "button";
    select.className = "outline-select";
    select.title = label;
    select.dataset.outlineTopic = key;
    select.dataset.presentationControl = "";
    select.addEventListener("click", () => selectTopic(key, command));
    if (ref) references.set(select, ref);
    if (children) {
      const toggle = node("button", "\u25be"), list = node("ul");
      list.id = `outline-${key}`;
      list.append(...children);
      toggle.type = "button";
      toggle.className = "outline-disclosure";
      toggle.dataset.outlineToggle = key;
      toggle.dataset.presentationControl = "";
      toggle.setAttribute("aria-label", `Collapse ${label}`);
      toggle.setAttribute("aria-expanded", "true");
      toggle.setAttribute("aria-controls", list.id);
      toggle.addEventListener("click", () => {
        list.hidden = !list.hidden;
        toggle.textContent = list.hidden ? "\u25b8" : "\u25be";
        toggle.setAttribute("aria-expanded", String(!list.hidden));
        toggle.setAttribute("aria-label", `${list.hidden ? "Expand" : "Collapse"} ${label}`);
      });
      row.append(toggle, select);
      li.append(row, list);
    } else {
      row.classList.add("outline-leaf");
      row.append(select);
      li.append(row);
    }
    return li;
  }
  function commandItems(group) {
    return commands.filter((button) => button.id !== "show-infrastructure" &&
      button.closest(".infrastructure-group") === group)
      .map((button) => item(button.textContent.trim(), `command-${button.dataset.phase || "view"}`,
        null, { setup: ":z5b", check: ":4nm", stop: ":p6y" }[button.dataset.phase], button));
  }
  $("outline-items").append(
    item("MRVA system summary", "system", null, ":7vj"),
    item("Workflow commands", "workflow", [
      item("Infrastructure", "infrastructure", [
        item("Setup", "setup", commandItems($("setup-heading").parentElement)),
        item("Maintenance", "maintenance", commandItems($("maintenance-heading").parentElement)),
        item("System view", "sysview", null, ":m3d"),
      ], ":k81"),
      item("Sessions", "sessions", null, ":f3a"),
      item("Comparison", "comparison", null, ":b4z"),
    ], ":a9x"),
  );
  function markOutline(key) {
    currentKey = key;
    outline.querySelectorAll("[data-outline-topic]").forEach((button) => {
      if (button.dataset.outlineTopic === key) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
  }
  function selectTopic(key, command) {
    markOutline(key);
    if (key === "sysview") {
      showDetail("sysview");
      return;
    }
    topic = key;
    selectedCommand = command;
    const infrastructure = ["infrastructure", "setup", "maintenance"].includes(key) || Boolean(command);
    panels.forEach((panel, index) => {
      panel.hidden = theme === "apple" && !(
        (index === 0 && key === "system") || (index === 1 && infrastructure) ||
        (index === 2 && key === "sessions") || (index === 3 && key === "comparison"));
    });
    $("outline-overview").hidden = key !== "workflow" || theme !== "apple";
    const selectedRow = outline.querySelector(`[data-outline-topic="${key}"]`);
    $("selection-title").textContent = selectedRow.textContent.trim();
    $("infrastructure-body").querySelectorAll(".infrastructure-group").forEach((group) => {
      const hide = command ? !group.contains(command)
        : key === "setup" ? group.getAttribute("aria-labelledby") !== "setup-heading"
          : key === "maintenance" && group.getAttribute("aria-labelledby") !== "maintenance-heading";
      group.toggleAttribute("data-apple-command-hidden", Boolean(hide));
    });
    commands.forEach((button) =>
      button.toggleAttribute("data-apple-command-hidden", Boolean(command && button !== command)),
    );
  }
  function refreshReferences() {
    if (theme === "apple") {
      for (const [button, ref] of references) window.CGAVID?.attach(button, ref);
    } else {
      outline.querySelectorAll(".cga-vid, .cga-vid-error").forEach((badge) => badge.remove());
    }
  }
  function updateOutlineVisibility() {
    const apple = theme === "apple", control = $("toggle-outline");
    if (apple && outlineCollapsed && outline.contains(document.activeElement)) control.focus();
    outline.hidden = !apple || outlineCollapsed;
    $("workflow-splitter").hidden = apple && outlineCollapsed;
    control.hidden = !apple;
    control.setAttribute("aria-expanded", String(!outlineCollapsed));
    control.title = outlineCollapsed ? "Show navigation" : "Hide navigation";
    control.setAttribute("aria-label", control.title);
    document.body.toggleAttribute("data-outline-collapsed", apple && outlineCollapsed);
  }
  $("toggle-outline").addEventListener("click", () => {
    outlineCollapsed = !outlineCollapsed;
    updateOutlineVisibility();
  });
  function apply(value, remember = true) {
    if (value === theme) return;
    theme = value;
    document.body.dataset.presentation = theme;
    const apple = theme === "apple";
    $("selection-panel").hidden = $("detail-splitter").hidden = !apple;
    updateOutlineVisibility();
    if (apple) {
      for (const id of ["system", "infrastructure", "sessions", "comparison"]) {
        const body = $(`${id}-body`), control = $(`collapse-${id}`);
        disclosureState.set(id, {
          hidden: body.hidden, text: control.textContent,
          expanded: control.getAttribute("aria-expanded"),
          label: control.getAttribute("aria-label"), title: control.title,
        });
        body.hidden = false;
        control.textContent = "\u25be";
        control.setAttribute("aria-expanded", "true");
        control.setAttribute("aria-label", `collapse ${id}`);
        control.title = `collapse ${id}`;
      }
      panels.forEach((panel) => $("selection-body").append(panel));
    } else {
      panels.forEach((panel, index) => { homes[index].after(panel); panel.hidden = false; });
      for (const [id, state] of disclosureState) {
        const control = $(`collapse-${id}`);
        $(`${id}-body`).hidden = state.hidden;
        control.textContent = state.text;
        control.setAttribute("aria-expanded", state.expanded);
        control.setAttribute("aria-label", state.label);
        control.title = state.title;
      }
    }
    buttons.forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.presentation === theme)));
    $("detail-placeholder").hidden = !apple || hasDetail;
    $("detail-panel").toggleAttribute("data-detail-empty", !hasDetail);
    const selectedOutline = currentKey;
    selectTopic(topic, selectedCommand);
    markOutline(selectedOutline);
    refreshReferences();
    if (remember) {
      try {
        localStorage.setItem("cga.bench.presentation", theme);
      } catch (error) {
        $("error").textContent = `Unable to save appearance: ${error.message}`;
      }
    }
    window.dispatchEvent(new Event("bench-presentation-change"));
  }
  buttons.forEach((button) => button.addEventListener("click", () => {
    apply(button.dataset.presentation);
    $("view-menu").open = false;
    $("view-menu").querySelector("summary").focus();
  }));
  outline.addEventListener("keydown", (event) => {
    const control = event.target.closest("[data-outline-topic], [data-outline-toggle]");
    if (!control) return;
    const li = control.closest("li"), toggle = li.querySelector(":scope > .outline-row > [data-outline-toggle]");
    const visible = [...outline.querySelectorAll("[data-outline-topic]")].filter((button) => button.getClientRects().length);
    const index = visible.indexOf(control.hasAttribute("data-outline-toggle")
      ? li.querySelector(":scope > .outline-row [data-outline-topic]") : control);
    let target;
    if (event.key === "ArrowDown") target = visible[Math.min(visible.length - 1, index + 1)];
    else if (event.key === "ArrowUp") target = visible[Math.max(0, index - 1)];
    else if (event.key === "Home") target = visible[0];
    else if (event.key === "End") target = visible.at(-1);
    else if (event.key === "ArrowRight" && toggle) {
      if (toggle.getAttribute("aria-expanded") === "false") toggle.click();
      else target = li.querySelector("ul [data-outline-topic]");
    } else if (event.key === "ArrowLeft") {
      if (toggle?.getAttribute("aria-expanded") === "true") toggle.click();
      else target = li.parentElement.closest("li")?.querySelector("[data-outline-topic]");
    } else return;
    event.preventDefault();
    target?.focus();
  });
  let initial = "apple";
  try {
    const saved = localStorage.getItem("cga.bench.presentation");
    if (["apple", "classic"].includes(saved)) initial = saved;
  } catch (error) {
    $("error").textContent = `Unable to read appearance preference: ${error.message}`;
  }
  apply(initial, false);
  const splitter = $("detail-splitter");
  let height = 48, dragging = false;
  function setHeight(value) {
    const total = workspace.clientHeight,
      minimum = Math.max(25, (140 / total) * 100),
      maximum = Math.max(minimum, Math.min(75, ((total - 168) / total) * 100));
    height = Math.max(minimum, Math.min(maximum, value));
    workspace.style.setProperty("--selection-pane-height", `${height}%`);
    splitter.setAttribute("aria-valuemin", String(Math.round(minimum)));
    splitter.setAttribute("aria-valuemax", String(Math.round(maximum)));
    splitter.setAttribute("aria-valuenow", String(Math.round(height)));
  }
  setHeight(height);
  splitter.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    splitter.setPointerCapture(event.pointerId);
    dragging = true;
    splitter.classList.add("dragging");
  });
  splitter.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    const box = workspace.getBoundingClientRect();
    setHeight(((event.clientY - box.top) / box.height) * 100);
  });
  for (const name of ["pointerup", "pointercancel", "lostpointercapture"]) {
    splitter.addEventListener(name, () => { dragging = false; splitter.classList.remove("dragging"); });
  }
  splitter.addEventListener("dblclick", () => setHeight(48));
  splitter.addEventListener("keydown", (event) => {
    if (!["ArrowUp", "ArrowDown", "Home"].includes(event.key)) return;
    event.preventDefault();
    setHeight(event.key === "Home" ? 48 : height + (event.key === "ArrowUp" ? -2 : 2));
  });
  window.addEventListener("resize", () => {
    if (theme === "apple") setHeight(height);
  });
  window.addEventListener("bench-presentation-change", () => {
    if (theme === "apple") setHeight(height);
  });
  return {
    isApple: () => theme === "apple",
    revealDetail(view) {
      if (view !== "sysview" && currentKey === "sysview") markOutline(topic);
      hasDetail = true;
      $("detail-panel").removeAttribute("data-detail-empty");
      $("detail-placeholder").hidden = true;
    },
    refresh: refreshReferences,
  };
}
async function request(path, options) {
  const response = await fetch(path, options),
    value = await response.json();
  if (!response.ok) throw new Error(value.error || response.statusText);
  if (
    value.schema === "cga.bench.view.v1" &&
    value.experiment.sessions.some((session) =>
      ["D", "Q", "R"].some((stage) =>
        !Array.isArray(session[stage].items) ||
        !Number.isInteger(session[stage].item_count)),
    )
  )
    throw new Error(
      "Bench server is out of date. Restart the viewer with 'cga bench stop' " +
        "then 'cga bench serve' using your previous options. Reloading the page is not enough.",
    );
  return value;
}
async function reload() {
  try {
    data = await request("api/view");
    render();
    await Promise.all([refreshSystem(), loadCollection(), loadResults()]);
  } catch (error) {
    $("error").textContent = error.message;
  }
}
function disableControls() {
  document
    .querySelectorAll("button")
    .forEach((button) => {
      if (!button.closest(".assistant-panel") && button.id !== "collapse-assistant" &&
          !button.hasAttribute("data-presentation-control"))
        button.disabled = busy;
    });
  modeButtons.forEach((button) => {
    button.disabled = busy || Boolean(
      data.experiment.mode && data.experiment.sessions.length,
    );
  });
  if (!busy) {
    const exp = data.experiment;
    $("new-session").querySelector("button").disabled = !exp.can_add;
    document.querySelectorAll("[data-mutation]").forEach((button) => {
      const session = exp.sessions[Number(button.dataset.session) - 1];
      button.disabled =
        button.dataset.mutation === "advance"
          ? !exp.mode ||
            session.R.status === "complete" ||
            session.D.status !== "complete" ||
            session.Q.status !== "complete"
          : !session[button.dataset.stage][`can_${button.dataset.mutation}`];
    });
    document
      .querySelectorAll('#grid input[type="checkbox"]')
      .forEach((checkbox) => {
        checkbox.disabled =
          exp.sessions[Number(checkbox.dataset.session) - 1].R.status !==
          "complete";
      });
    $("compare").disabled =
      !exp.mode ||
      exp.sessions[0]?.R.status !== "complete" ||
      !exp.sessions.slice(1).some((session) => session.R.status === "complete");
    $("copy-query").querySelector("button").disabled =
      $("copy-query").elements.from_session.value === "library" &&
      picked.size !== 1;
    $("rescan-catalogues").disabled = scanning;
    $("previous-page").disabled = !page || page.offset === 0;
    $("next-page").disabled = !page || !page.has_more;
    $("use-selection").disabled = !page || picked.size === 0;
  }
}
async function action(document) {
  if (busy) return;
  busy = true;
  $("error").textContent = "";
  disableControls();
  try {
    data = await request("api/action", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CGA-Bench": "1" },
      body: JSON.stringify(document),
    });
    if (document.action === "infrastructure")
      infrastructureRun = { phase: document.phase, status: "complete" };
    if (document.action === "copy-query") {
      sources.set(`${document.session}:Q`, "user");
      if (selected?.index === document.session && selected.stage === "Q")
        $("input-source").value = "user";
      editorKey = "";
    }
    render();
    await Promise.all([refreshSystem(), loadCollection(), loadResults()]);
  } catch (error) {
    $("error").textContent = error.message;
    if (document.action === "infrastructure")
      infrastructureRun = {
        phase: document.phase,
        status: "failed",
        error: error.message,
      };
    await reload();
  } finally {
    busy = false;
    disableControls();
  }
}
function summaryCard(label, value, note) {
  const card = node("div");
  card.className = "summary-card";
  card.append(
    node("span", label),
    node("strong", String(value)),
    node("span", note || ""),
  );
  return card;
}
function countStates(rows) {
  const counts = new Map();
  for (const row of rows) {
    const status = row.status == null ? "unknown" : String(row.status);
    counts.set(status, (counts.get(status) || 0) + 1);
  }
  return Object.fromEntries(counts);
}
async function refreshSystem() {
  const epoch = ++systemRequest;
  try {
    const response = await fetch("api/sysview", { cache: "no-store" }),
      payload = await response.json();
    if (!response.ok && payload.available !== false)
      throw new Error(payload.error || response.statusText);
    if (epoch !== systemRequest) return;
    systemSnapshot = payload;
  } catch (error) {
    if (epoch !== systemRequest) return;
    systemSnapshot = {
      available: false,
      error: error.message,
      url: data?.system.url,
    };
  }
  if (data) renderSystem();
}
function renderSystem() {
  let system = data.system,
    runtime;
  if (systemSnapshot) {
    const snapshot = systemSnapshot.data || {},
      servers = snapshot.servers || [],
      workers = snapshot.workers || [],
      jobs = snapshot.jobs || [],
      spawns = snapshot.spawns || [];
    system = {
      available: systemSnapshot.available,
      error: systemSnapshot.error,
      servers_online: servers.filter((server) => server.online).length,
      servers_total: servers.length,
      workers: workers.length,
      jobs: jobs.length,
      spawns: spawns.length,
      served_by: snapshot.served_by,
      generated_at: snapshot.generated_at,
      url: systemSnapshot.url,
    };
    runtime = {
      servers,
      worker_states: countStates(workers),
      job_states: countStates(jobs),
    };
  }
  $("system-availability").textContent = system.available ? "live" : "offline";
  $("sysview-link").href = system.url;
  renderSystemView(system);
  $("system-detail").replaceChildren();
  if (!system.available) {
    $("system-summary").replaceChildren(
      summaryCard("MRVA", "offline", system.error),
    );
    return;
  }
  $("system-summary").replaceChildren(
    summaryCard(
      "servers online",
      system.servers_online,
      `${system.servers_total} known`,
    ),
    summaryCard(
      "workers",
      system.workers,
      runtime ? `${Object.keys(runtime.worker_states).length} states` : "",
    ),
    summaryCard(
      "jobs",
      system.jobs,
      runtime ? `${Object.keys(runtime.job_states).length} states` : "",
    ),
    summaryCard("pending spawns", system.spawns),
    summaryCard("served by", system.served_by || "-", system.generated_at),
  );
  if (!runtime) {
    $("system-detail").append(node("p", "Loading runtime details..."));
    return;
  }
  const servers = node("div"),
    counts = node("div");
  servers.className = counts.className = "runtime-card";
  servers.append(
    node("h3", "Servers"),
    node(
      "pre",
      runtime.servers.length
        ? runtime.servers
            .map(
              (server) =>
                `${server.role || "server"}: ${server.instance_id || "unknown"} \u00b7 ${server.online ? "online" : "offline"}`,
            )
            .join("\n")
        : "No registered servers.",
    ),
  );
  counts.append(
    node("h3", "Runtime counts"),
    node(
      "pre",
      `job states: ${JSON.stringify(runtime.job_states)}\n` +
        `worker states: ${JSON.stringify(runtime.worker_states)}\n` +
        `pending spawns: ${system.spawns}`,
    ),
  );
  $("system-detail").append(servers, counts);
}
function renderSystemView(system) {
  const frame = $("sysview-frame");
  if (detailView !== "sysview" || !system.available) {
    frame.removeAttribute("src");
    frame.removeAttribute("data-loaded");
    frame.hidden = true;
    $("sysview-error").textContent = detailView === "sysview"
      ? `MRVA system view is offline: ${system.error || "MRVA is unavailable."}` : "";
    return;
  }
  frame.hidden = false;
  if (frame.getAttribute("src") !== system.url) {
    systemFrameError = "";
    frame.removeAttribute("data-loaded");
    frame.src = system.url;
  }
  $("sysview-error").textContent = systemFrameError;
}
function sessionCell(session, stage, compact) {
  const td = node("td");
  td.dataset.stage = stage;
  if (stage === "compare") {
    const checkbox = node("input");
    checkbox.type = "checkbox";
    checkbox.dataset.session = session.index;
    checkbox.setAttribute("aria-label", `compare session ${session.index}`);
    checkbox.disabled = session.R.status !== "complete";
    checkbox.checked = chosen.has(session.index);
    checkbox.addEventListener("change", () =>
      checkbox.checked ? chosen.add(session.index) : chosen.delete(session.index),
    );
    td.append(checkbox);
  } else if (stage === "action") {
    if (compact && session.R.status === "complete") {
      const idle = node("span", "\u2014");
      idle.setAttribute("aria-label", "No action required");
      td.append(idle);
    } else {
      const advance = node("button", session.J.status === "running" ? "Check progress" : "Continue");
      advance.dataset.session = session.index;
      advance.dataset.mutation = "advance";
      advance.addEventListener("click", () => action({ action: "advance", session: session.index }));
      td.append(advance);
    }
  } else {
    const cell = session[stage], button = node("button");
    button.className = cell.status;
    if (compact) {
      const symbol = node("span", {
        empty: "\u25cb", blocked: "\u25cb", running: "\u25d0", complete: "\u2713", failed: "\u00d7",
      }[cell.status] || cell.status);
      symbol.setAttribute("aria-hidden", "true");
      button.append(symbol);
      button.classList.add("status-button");
      button.title = `${cell.status}${cell.summary || cell.requirement ? `: ${cell.summary || cell.requirement}` : ""}`;
    } else {
      button.textContent = cell.status;
      button.title = cell.summary || cell.requirement;
    }
    button.dataset.session = session.index;
    button.dataset.stage = stage;
    button.setAttribute("aria-label", `session ${session.index}, ${stage}: ${cell.status}`);
    button.setAttribute("aria-pressed", String(
      detailView === "cell" && selected?.index === session.index && selected?.stage === stage,
    ));
    button.addEventListener("click", () => selectCell(session.index, stage));
    td.append(button);
    window.CGAVID?.attach(button, cell.vid);
    if (["D", "Q"].includes(stage)) {
      const operation = cell.can_edit ? "edit" : cell.can_clone ? "clone" : null;
      if (operation) {
        const control = node("button", operation === "edit" ? "Edit" : "Clone...");
        control.dataset.session = session.index;
        control.dataset.stage = stage;
        control.dataset.mutation = operation;
        control.setAttribute("aria-label", `${operation} session ${session.index} ${stage}`);
        control.addEventListener("click", () => selectCell(session.index, stage));
        if (compact) {
          const actions = node("div");
          actions.className = "session-cell-actions";
          actions.append(control);
          td.append(actions);
        } else td.append(control);
      }
    }
  }
  return td;
}
function sessionHeading(session, compact) {
  const th = node("th"), reference = session.index === 1 ? " Reference" : "",
    title = node("span", compact ? `S${session.index}${reference}` : `${session.index}${reference} (${session.status})`);
  th.scope = compact ? "row" : "col";
  th.dataset.session = session.index;
  if (compact) th.setAttribute("aria-label", `Session ${session.index}${reference}: ${session.status}`);
  title.title = `Session ${session.index}${reference}: ${session.status}`;
  th.append(title);
  window.CGAVID?.attach(title, session.vid);
  return th;
}
function renderGrid() {
  window.CGAVID?.setContext(data.vid_context);
  presentation?.refresh();
  const sessions = data.experiment.sessions, compact = presentation?.isApple(),
    stages = [
      ["compare", "Compare"], ["D", "Database D"], ["Q", "Query Q"],
      ["J", "Job J"], ["R", "Result R"], ["action", "Action"],
    ],
    heading = node("tr");
  document.querySelector(".session-grid").classList.toggle("session-rows", Boolean(compact));
  $("session-status-legend").hidden = !compact;
  if (compact) {
    for (const [key, title] of [["compare", "Compare"], ["session", "Session"], ...stages.slice(1)]) {
      const th = node("th", ["D", "Q", "J", "R"].includes(key) ? key : title);
      th.scope = "col";
      th.title = title;
      heading.append(th);
    }
  } else {
    const label = node("th", "Session");
    label.scope = "col";
    heading.append(label, ...sessions.map((session) => sessionHeading(session, false)));
  }
  $("grid-head").replaceChildren(heading);
  $("grid").replaceChildren();
  if (!sessions.length) {
    const row = node("tr"), cell = node("td", "No sessions yet. Add a session to begin.");
    cell.colSpan = compact ? 7 : 1;
    row.append(cell);
    $("grid").append(row);
  } else if (compact) {
    for (const session of sessions) {
      const row = node("tr");
      row.dataset.session = session.index;
      row.append(sessionCell(session, "compare", true), sessionHeading(session, true),
        ...stages.slice(1).map(([stage]) => sessionCell(session, stage, true)));
      $("grid").append(row);
    }
  } else {
    for (const [stage, title] of stages) {
      const row = node("tr"), th = node("th", title);
      row.dataset.stage = stage;
      th.scope = "row";
      row.append(th, ...sessions.map((session) => sessionCell(session, stage, false)));
      $("grid").append(row);
    }
  }
}
function renderSelectedDetail() {
  $("infrastructure-detail").hidden = detailView !== "infrastructure";
  $("cell-detail").hidden = detailView !== "cell";
  $("comparison-detail").hidden = detailView !== "comparison";
  $("sysview-detail").hidden = detailView !== "sysview";
  $("show-infrastructure").setAttribute(
    "aria-pressed",
    String(detailView === "infrastructure"),
  );
  $("show-comparison").setAttribute(
    "aria-pressed",
    String(detailView === "comparison"),
  );
  $("infrastructure-status").textContent = data.infrastructure.setup_failed
    ? "Automatic setup needs attention. Check services or ask your assistant."
    : `Last action: ${data.infrastructure.actions[data.infrastructure.last_phase] || "Not prepared"}`;
  $("infrastructure-error").textContent = infrastructureRun?.error || "";
  $("infrastructure-action-status").textContent = infrastructureRun
    ? `${infrastructureLabel(infrastructureRun.phase)}: ${infrastructureRun.status === "running" ? "running..." : infrastructureRun.status === "failed" ? "failed" : "completed"}`
    : "";
  if (detailView === "infrastructure") {
    $("address").textContent = infrastructureDetailPhase
      ? `Detail: ${infrastructureLabel(infrastructureDetailPhase)}`
      : "Detail: Infrastructure";
  } else if (detailView === "comparison") {
    $("address").textContent = "Detail: Comparison E.C";
  } else if (detailView === "sysview") {
    $("address").textContent = "Detail: MRVA system view";
  } else {
    renderDetail();
  }
}
function render() {
  const exp = data.experiment;
  $("experiment").textContent = `${exp.name} (${exp.sessions.length} sessions)`;
  modeButtons.forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.mode === exp.mode));
  });
  $("mode-guidance").textContent = exp.mode
    ? `Experiment mode: ${modeButtons.find((button) => button.dataset.mode === exp.mode).textContent.trim()}.`
    : "Choose an experiment mode in the Mode menu before preparing sessions.";
  $("mode-status").textContent = !exp.mode
    ? "Select a mode explicitly in the Mode menu before preparing sessions."
    : "Session 1 (S1) is the reference. " +
      (exp.fixed_stage === "D"
        ? "Database selection D is fixed; the Query Q is editable."
        : "Query Q is fixed; the Database selection D is editable.") +
      (!exp.can_add
        ? ` Accept S1's ${exp.fixed_stage} before adding a variant.`
        : "");
  renderSystem();
  renderGrid();
  renderSelectedDetail();
  renderComparison();
  disableControls();
}
function showDetail(view, phase) {
  presentation?.revealDetail(view);
  if (view === "sysview") {
    $("sysview-frame").removeAttribute("src");
    systemFrameError = "";
  }
  detailView = view;
  infrastructureDetailPhase = phase;
  selectionRequest++;
  resultRequest++;
  resultLoading = false;
  if (data) render();
}
function selectSessionTab(stage) {
  sessionTab = stage;
  for (const value of ["D", "Q", "R", "F"]) {
    const active = value === stage;
    $(`session-tab-${value}`).setAttribute("aria-selected", String(active));
    $(`session-tab-${value}`).tabIndex = active ? 0 : -1;
    $(`session-panel-${value}`).hidden = !active;
  }
}
function evidenceLink(label, session, stage) {
  const link = node("a", label);
  link.href = `evidence?${new URLSearchParams({ session, stage })}`;
  link.target = `cga-bench-evidence-${location.host}-${session}-${stage}`;
  link.addEventListener("click", (event) => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    $("session-evidence-error").textContent = "";
    let popup = evidencePopups.get(link.target);
    if (!popup || popup.closed) {
      popup = window.open(link.href, link.target, "popup,width=1100,height=800,resizable=yes,scrollbars=yes");
      if (popup) evidencePopups.set(link.target, popup);
    }
    if (!popup) {
      $("session-evidence-error").textContent =
        "Allow pop-ups for this Bench page, then click the evidence link again.";
      return;
    }
    popup.focus();
  });
  return link;
}
function renderSessionEvidence(session) {
  for (const [stage, title, columns, empty] of [
    [
      "D", "Accepted databases",
      [["repository", "Repository"], ["archive", "Archive"], ["sha256", "SHA-256"]],
      "No accepted databases yet.",
    ],
    [
      "Q", "Accepted queries",
      [["name", "Name"], ["id", "Query ID"], ["language", "Language"], ["path", "Source"]],
      "No accepted queries yet.",
    ],
    [
      "R", "Result summary",
      [["repository", "Repository"], ["finding_count", "Findings"]],
      "No repository results yet.",
    ],
  ]) {
    const cell = session[stage],
      panel = $(`session-panel-${stage}`),
      heading = node("h3", title);
    panel.replaceChildren(heading);
    window.CGAVID?.attach(heading, cell.vid);
    if (stage === "R") {
      const summary = cell.summary || cell.requirement || "Results not available yet.";
      panel.append(node("p", `${cell.status}: ${summary}`));
    }
    const kind = { D: "databases", Q: "queries", R: "repository summaries" }[stage],
      link = evidenceLink(`Browse all ${kind} / SQL`, session.index, stage);
    const count = node("p", `Count: ${cell.item_count}. ${cell.item_count ? "Showing the first row." : "No preview rows."}`);
    count.className = "session-preview-count";
    panel.append(count);
    panel.append(link);
    if (!cell.items.length) {
      panel.append(node("p", empty));
      continue;
    }
    const scroll = node("div"),
      table = node("table"),
      head = node("thead"),
      header = node("tr"),
      body = node("tbody");
    scroll.className = "table-scroll";
    table.setAttribute("aria-label", title);
    for (const [, label] of columns) {
      const th = node("th", label);
      th.scope = "col";
      header.append(th);
    }
    head.append(header);
    cell.items.slice(0, 1).forEach((item, index) => {
      const row = node("tr");
      for (const [key] of columns) row.append(node("td", item[key] ?? "-"));
      const ref = stage === "Q"
        ? `${cell.vid},${index + 1}`
        : cell.children.find(child => child.label === item.repository)?.ref;
      if (ref) window.CGAVID?.attach(row.firstChild, ref);
      body.append(row);
    });
    table.append(head, body);
    scroll.append(table);
    panel.append(scroll);
  }
  $("findings-summary").textContent =
    session.R.summary || session.R.requirement || "Findings are not available yet.";
  window.CGAVID?.attach($("findings-heading"), session.R.vid);
  $("findings-link").replaceChildren();
  if (session.R.status === "complete")
    $("findings-link").append(evidenceLink("Browse all findings / SQL", session.index, "F"));
  $("result-head").replaceChildren();
  $("result-rows").replaceChildren();
  $("result-status").textContent = session.R.status === "complete" ? "Loading findings preview..." : "";
  $("result-error").textContent = "";
  selectSessionTab(sessionTab);
}
function renderDetail() {
  if (detailView !== "cell" || !selected) return;
  const session = data.experiment.sessions[selected.index - 1],
    cell = session[selected.stage];
  $("address").textContent =
    `Detail: session ${selected.index}, stage ${selected.stage}`;
  $("cell-status").hidden = false;
  $("requirement").textContent = cell.requirement || "No missing input";
  $("artifact-summary").textContent = cell.summary;
  renderSessionEvidence(session);
  $("cell-elements").replaceChildren();
  if (selected.stage === "J") {
    for (const child of cell.children) {
      const label = node("span", child.label);
      $("cell-elements").append(label);
      window.CGAVID?.attach(label, child.ref);
    }
  }
  const input = ["D", "Q"].includes(selected.stage),
    fixed = selected.stage === data.experiment.fixed_stage;
  $("input-role").textContent = !input
    ? "Derived from running this session; not user input."
    : !data.experiment.mode
      ? "Select an experiment mode to prepare inputs."
      : fixed
        ? `Fixed ${selected.stage} input${cell.cloned_from ? `: cloned from S${cell.cloned_from.session}` : selected.index === 1 ? " established by S1" : ": clone from a prior session"}.`
        : `Editable ${selected.stage} input for this experiment.`;
  $("workspace").hidden = !cell.can_edit;
  $("clone-input").hidden = !cell.can_clone;
  if (cell.can_clone) {
    const choices = $("clone-input").elements.from_session,
      previous = choices.value;
    choices.replaceChildren(
      ...data.experiment.sessions
        .filter(
          (prior) =>
            prior.index < selected.index &&
            prior[selected.stage].status === "complete",
        )
        .map((prior) => {
          const option = node(
            "option",
            `S${prior.index}${prior.index === 1 ? " Reference" : ""}`,
          );
          option.value = prior.index;
          return option;
        }),
    );
    choices.value = [...choices.options].some(
      (option) => option.value === previous,
    )
      ? previous
      : "1";
  }
  const database = selected.stage === "D",
    user = inputSource() === "user",
    key = `${selected.index}:${selected.stage}`;
  $("database-input-source").hidden = !database;
  $("query-input-source").hidden = selected.stage !== "Q";
  $("database-preparation").hidden = !database;
  $("query-preparation").hidden = selected.stage !== "Q" || user;
  $("catalogue-discovery").hidden = !database;
  if (detailKey !== key) {
    $("load-catalogue").elements.path.value = session.libraries.catalogue;
    $("index-library").elements.directory.value =
      session.libraries.query_directory;
    detailKey = key;
  }
  syncCatalogueChoice();
  $("catalogue-status").textContent = session.libraries.databases_loaded
    ? "Database catalogue loaded"
    : "No database catalogue loaded";
  $("library-status").textContent = session.libraries.queries_loaded
    ? "Query library indexed"
    : "No query library indexed";
  $("selection-workspace").hidden = $("workspace").hidden;
  $("user-query").hidden = selected.stage !== "Q" || !user;
  $("query-editor").hidden = !session.has_query_workspace;
  $("copy-query").hidden = selected.stage !== "Q" || !cell.can_edit;
  if (selected.stage === "Q" && cell.can_edit) {
    const choices = $("copy-query").elements.from_session,
      previous = choices.value;
    choices.replaceChildren(node("option", "Selected library query"));
    choices.options[0].value = "library";
    for (const prior of data.experiment.sessions) {
      if (prior.index >= selected.index || prior.Q.status !== "complete")
        continue;
      const option = node("option", `Accepted query from S${prior.index}`);
      option.value = prior.index;
      choices.append(option);
    }
    choices.value = [...choices.options].some(
      (option) => option.value === previous,
    )
      ? previous
      : "library";
    if ($("copy-query").dataset.session !== String(selected.index)) {
      $("copy-query").elements.directory.value =
        `${data.libraries.query_workspaces}/session-${selected.index}-draft`;
      $("copy-query").dataset.session = selected.index;
    }
  }
  $("history").replaceChildren(
    ...cell.history.map((entry) =>
      node("li", `${entry.text} (${new Date(entry.at).toLocaleString()})`),
    ),
  );
  if (session.R.status !== "complete") {
    resultPage = undefined;
    resultRequest++;
    resultLoading = false;
  }
}
async function selectCell(index, stage) {
  presentation?.revealDetail();
  detailView = "cell";
  selected = { index, stage };
  sessionTab = ["D", "Q", "R"].includes(stage) ? stage : "R";
  const session = data.experiment.sessions[index - 1];
  $("input-source").value = sources.get(`${index}:${stage}`) || "list";
  picked.clear();
  page = null;
  offset = 0;
  pickerKey = "";
  $("collection-search").elements.search.value = "";
  $("create-query").elements.language.value = session.D.language || "cpp";
  $("create-query").elements.directory.value =
    `${data.libraries.query_workspaces}/${$("create-query").elements.name.value}`;
  render();
  await Promise.all([
    loadCollection(),
    loadResults(),
    stage === "D" && !$("catalogue-discovery").hidden && !$("workspace").hidden
      ? loadCatalogues()
      : Promise.resolve(),
  ]);
}
async function loadResults() {
  if (
    detailView !== "cell" ||
    !selected ||
    data.experiment.sessions[selected.index - 1].R.status !== "complete"
  )
    return;
  const session = selected.index,
    epoch = ++resultRequest;
  resultLoading = true;
  resultPage = undefined;
  $("result-status").textContent = "Loading session results...";
  $("result-error").textContent = "";
  $("result-head").replaceChildren();
  $("result-rows").replaceChildren();
  disableControls();
  try {
    const value = await request("api/results", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CGA-Bench": "1" },
      body: JSON.stringify({
        session,
        offset: 0,
        limit: 1,
      }),
    });
    if (
      epoch !== resultRequest ||
      detailView !== "cell" ||
      selected?.index !== session
    )
      return;
    resultPage = value;
    const labels = {
      repository: "Repository",
      rule_id: "Rule ID",
      rule_name: "Rule name",
      kind: "Kind",
      uri: "File URI",
      start_line: "Line",
      start_column: "Column",
      message: "Message",
    };
    const head = node("tr");
    value.columns.forEach((column) =>
      head.append(node("th", labels[column] || column)),
    );
    $("result-head").replaceChildren(head);
    for (const row of value.rows) {
      const tr = node("tr");
      value.columns.forEach((column) => {
        const entry = row[column];
        tr.append(
          node(
            "td",
            entry == null
              ? ""
              : typeof entry === "object"
                ? JSON.stringify(entry)
                : String(entry),
          ),
        );
      });
      $("result-rows").append(tr);
    }
    $("result-status").textContent =
      `Count: ${value.finding_count}. ` +
      (value.rows.length ? "Showing the first row." : "No findings in this session.");
  } catch (error) {
    if (epoch === resultRequest) {
      $("result-error").textContent = error.message;
      $("result-status").textContent =
        "Findings preview failed. Reload or open the findings popup to retry.";
    }
  } finally {
    if (epoch === resultRequest) {
      resultLoading = false;
      disableControls();
    }
  }
}
function syncCatalogueChoice() {
  const input = $("load-catalogue").elements.path;
  $("catalogue-options").value = catalogues?.paths.includes(input.value)
    ? input.value
    : "";
}
async function loadCatalogues(refresh = false) {
  if (scanning || (catalogues && !refresh)) return;
  scanning = true;
  $("catalogue-discovery-status").textContent =
    "Looking for metadata.sql files...";
  disableControls();
  try {
    catalogues = await request("api/catalogues");
    const placeholder = node("option", "Choose a discovered catalogue");
    placeholder.value = "";
    $("catalogue-options").replaceChildren(
      placeholder,
      ...catalogues.paths.map((path) => {
        const option = node("option", path);
        option.value = path;
        return option;
      }),
    );
    syncCatalogueChoice();
    const outline = node("ul"),
      searched = node("li", "Searched:"),
      roots = node("ul");
    roots.append(...catalogues.roots.map((root) => node("li", root)));
    searched.append(roots);
    outline.append(
      node("li", `${catalogues.paths.length} found.`),
      searched,
      node(
        "li",
        "Hidden/dependency directories and directory symlinks are not scanned; " +
          "the suggested collection catalogue is also checked. " +
          "Choose a file above or enter a path/URL below, then load it.",
      ),
    );
    $("catalogue-discovery-status").replaceChildren(outline);
  } catch (error) {
    $("catalogue-discovery-status").textContent = error.message;
  } finally {
    scanning = false;
    disableControls();
  }
}
async function loadCollection() {
  const sequence = ++selectionRequest;
  if (
    detailView !== "cell" ||
    !selected ||
    !["D", "Q"].includes(selected.stage) ||
    $("selection-workspace").hidden
  )
    return;
  const kind = selected.stage === "D" ? "databases" : "queries";
  const source = inputSource();
  const params = new URLSearchParams({
    session: selected.index,
    source,
    search: $("collection-search").elements.search.value,
    offset,
    limit: 30,
  });
  try {
    const value = await request(`api/collections/${kind}?${params}`);
    if (sequence !== selectionRequest) return;
    const key = `${selected.index}:${kind}:${source}:${value.generation}`;
    if (key !== pickerKey) {
      picked.clear();
      pickerKey = key;
    }
    page = value;
    renderCollection();
  } catch (error) {
    if (sequence !== selectionRequest) return;
    page = null;
    picked.clear();
    $("collection-head").replaceChildren();
    $("collection-rows").replaceChildren();
    $("collection-status").textContent =
      source === "user" && selected.stage === "Q"
        ? "Create a query workspace to start developing your query."
        : error.message;
    $("use-selection").disabled = true;
  }
  if (selected.stage === "Q" && source === "user") await loadEditor(sequence);
}
function renderCollection() {
  const database = selected.stage === "D";
  const columns = database
    ? [
        ["git_owner", "Owner"],
        ["git_repo", "Repository"],
        ["primary_language", "Language"],
        ["tool_version", "CodeQL version"],
      ]
    : [
        ["name", "Name"],
        ["id", "Query ID"],
        ["language", "Language"],
        ["description", "Description"],
      ];
  const header = node("tr");
  header.append(node("th", "Choose"));
  columns.forEach(([, label]) => header.append(node("th", label)));
  $("collection-head").replaceChildren(header);
  $("collection-rows").replaceChildren();
  for (const row of page.rows) {
    const tr = node("tr"),
      control = node("input");
    control.type = database ? "checkbox" : "radio";
    control.name = "library-row";
    control.checked = picked.has(row._row);
    control.setAttribute(
      "aria-label",
      database
        ? `${row.git_owner}/${row.git_repo}`
        : row.name || row.id || row.relpath,
    );
    control.addEventListener("change", () => {
      if (!database) picked.clear();
      if (control.checked) picked.add(row._row);
      else picked.delete(row._row);
      updatePick();
    });
    const td = node("td");
    td.append(control);
    tr.append(td);
    columns.forEach(([key]) => tr.append(node("td", String(row[key] || ""))));
    $("collection-rows").append(tr);
    window.CGAVID?.attach(control, row.vid);
  }
  $("collection-status").textContent =
    `${page.offset + (page.rows.length ? 1 : 0)}-${page.offset + page.rows.length} of ${page.total}`;
  updatePick();
}
function updatePick() {
  $("selection-count").textContent = `${picked.size} selected`;
  $("use-selection").textContent =
    selected.stage === "D"
      ? "Use selected databases"
      : "Use query and continue";
  disableControls();
}
async function loadEditor(sequence) {
  const session = data.experiment.sessions[selected.index - 1];
  if (!session.has_query_workspace) return;
  try {
    const value = await request(`api/query-source?session=${selected.index}`);
    if (sequence !== selectionRequest) return;
    const key = `${selected.index}:${value.directory}`;
    if (editorKey !== key) {
      $("save-query").elements.source.value = value.source;
      editorKey = key;
    }
    $("query-file").textContent = `${value.name} in ${value.directory}`;
    $("pack-manifest").textContent = value.manifest;
    $("query-editor").hidden = false;
  } catch (error) {
    $("error").textContent = error.message;
  }
}
function findingTable(rows) {
  const table = node("table"),
    head = node("tr");
  ["Repository", "Rule", "Location", "Message"].forEach((label) =>
    head.append(node("th", label)),
  );
  table.append(head);
  for (const row of rows) {
    const id = row.identity,
      tr = node("tr");
    const locations = (id.locations || [])
      .map(
        (location) =>
          `${location.uri || ""}:${location.region?.startLine || ""}`,
      )
      .join(", ");
    [
      id.repository || "",
      id.rule || "",
      locations,
      id.message?.text || id.message?.markdown || "",
    ].forEach((value) => tr.append(node("td", value)));
    table.append(tr);
  }
  return table;
}
function renderComparison() {
  const comparison = data.comparison;
  $("comparison").replaceChildren();
  $("comparison-inputs").textContent = comparison
    ? comparison.sessions.map((session) => session.address).join(" -> ")
    : "";
  if (!comparison) {
    $("comparison").append(
      node(
        "p",
        "No comparison yet. Choose completed sessions and compare them.",
      ),
    );
    return;
  }
  $("comparison").append(
    node(
      "p",
      `${comparison.common.length} common findings. Changes are relative to the first selected session.`,
    ),
  );
  for (const session of comparison.sessions) {
    const details = node("details");
    details.append(
      node(
        "summary",
        `${session.address}: ${session.finding_count} findings, ${session.added.length} added, ${session.removed.length} removed`,
      ),
    );
    details.append(
      node("h3", "Added"),
      findingTable(session.added),
      node("h3", "Removed"),
      findingTable(session.removed),
    );
    $("comparison").append(details);
  }
  const common = node("details");
  common.append(
    node("summary", "Common findings"),
    findingTable(comparison.common),
  );
  $("comparison").append(common);
}
function infrastructureLabel(phase) {
  return (
    {
      setup: "Prepare services",
      check: "Check services",
      stop: "Stop services",
    }[phase] || data.infrastructure.actions[phase]
  );
}
async function infrastructure(phase) {
  if (busy) return;
  const destructive = ["preflight", "reset", "cleanup"].includes(phase);
  if (
    destructive &&
    !confirm(
      "This maintenance action can stop services or erase MRVA runtime state. Continue?",
    )
  )
    return;
  infrastructureRun = { phase, status: "running" };
  showDetail("infrastructure", phase);
  await action({ action: "infrastructure", phase, confirmed: destructive });
}
$("show-infrastructure").addEventListener("click", () =>
  showDetail("infrastructure"),
);
$("show-comparison").addEventListener("click", () => showDetail("comparison"));
$("sysview-frame").addEventListener("load", () => {
  if ($("sysview-frame").hasAttribute("src")) $("sysview-frame").dataset.loaded = "true";
});
$("sysview-frame").addEventListener("error", () => {
  systemFrameError = "Unable to load MRVA system view. Use View > live system to open it separately.";
  $("sysview-error").textContent = systemFrameError;
});
document.addEventListener("securitypolicyviolation", (event) => {
  if (event.effectiveDirective !== "frame-src" || detailView !== "sysview") return;
  systemFrameError =
    "The viewer's frame policy blocks MRVA system view. Restart Bench, or use View > live system.";
  $("sysview-error").textContent = systemFrameError;
});
document
  .querySelectorAll("[data-phase]")
  .forEach((button) =>
    button.addEventListener("click", () =>
      infrastructure(button.dataset.phase),
    ),
  );
for (const [phase, label] of [
  ["preflight", "Check and reclaim service ports"],
  ["reset", "Reset MRVA state"],
  ["build", "Rebuild services"],
  ["cleanup", "Clean MRVA runtime"],
]) {
  const button = node("button", label);
  button.dataset.phase = phase;
  button.addEventListener("click", () => infrastructure(phase));
  $("maintenance").append(button);
}
$("reload").addEventListener("click", reload);
document.querySelectorAll("[data-session-tab]").forEach((tab) => {
  tab.addEventListener("click", () => selectSessionTab(tab.dataset.sessionTab));
  tab.addEventListener("keydown", (event) => {
    const stages = ["D", "Q", "R", "F"],
      index = stages.indexOf(tab.dataset.sessionTab);
    const next = {
      ArrowRight: stages[(index + 1) % stages.length],
      ArrowLeft: stages[(index + stages.length - 1) % stages.length],
      Home: "D",
      End: "F",
    }[event.key];
    if (!next) return;
    event.preventDefault();
    selectSessionTab(next);
    $(`session-tab-${next}`).focus();
  });
});
$("rescan-catalogues").addEventListener("click", () => loadCatalogues(true));
$("catalogue-options").addEventListener("change", (event) => {
  if (!event.target.value) return;
  $("load-catalogue").elements.path.value = event.target.value;
});
$("load-catalogue").elements.path.addEventListener(
  "input",
  syncCatalogueChoice,
);
$("new-session").addEventListener("submit", (event) => {
  event.preventDefault();
  action({ action: "session" });
});
modeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    action({ action: "mode", mode: button.dataset.mode });
    $("mode-menu").open = false;
    $("experiment-mode").focus();
  });
});
const headerMenus = [...document.querySelectorAll(".header-menu")];
headerMenus.forEach((menu) => {
  menu.addEventListener("toggle", () => {
    if (menu.open) headerMenus.forEach((other) => {
      if (other !== menu) other.open = false;
    });
  });
  menu.addEventListener("click", (event) => {
    if (event.target.closest("#collapse-assistant, #sysview-link")) menu.open = false;
  });
});
document.addEventListener("click", (event) => {
  headerMenus.forEach((menu) => {
    if (!menu.contains(event.target)) menu.open = false;
  });
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  headerMenus.forEach((menu) => {
    if (!menu.open) return;
    menu.open = false;
    menu.querySelector("summary").focus();
  });
});
$("clone-input").addEventListener("submit", (event) => {
  event.preventDefault();
  action({
    action: "clone",
    session: selected.index,
    stage: selected.stage,
    from_session: Number(event.target.elements.from_session.value),
  });
});
$("copy-query").elements.from_session.addEventListener(
  "change",
  disableControls,
);
$("copy-query").addEventListener("submit", async (event) => {
  event.preventDefault();
  const from = event.target.elements.from_session.value;
  if (from === "library" && (!page || picked.size !== 1)) {
    $("error").textContent = "Choose one library query to copy into a draft.";
    return;
  }
  const document = {
    action: "copy-query",
    session: selected.index,
    directory: event.target.elements.directory.value,
    ...(from === "library"
      ? {
          generation: page.generation,
          row: [...picked][0],
          source: inputSource(),
        }
      : { from_session: Number(from) }),
  };
  await action(document);
});
$("load-catalogue").addEventListener("submit", (event) => {
  event.preventDefault();
  action({
    action: "catalogue",
    session: selected.index,
    ...fields(event.target),
  });
});
$("index-library").addEventListener("submit", (event) => {
  event.preventDefault();
  action({
    action: "library",
    session: selected.index,
    ...fields(event.target),
  });
});
$("input-source").addEventListener("change", () => {
  sources.set(`${selected.index}:${selected.stage}`, $("input-source").value);
  offset = 0;
  pickerKey = "";
  picked.clear();
  renderDetail();
  loadCollection();
});
$("collection-search").addEventListener("submit", (event) => {
  event.preventDefault();
  offset = 0;
  loadCollection();
});
$("previous-page").addEventListener("click", () => {
  offset = Math.max(0, offset - 30);
  loadCollection();
});
$("next-page").addEventListener("click", () => {
  offset += 30;
  loadCollection();
});
$("use-selection").addEventListener("click", () =>
  action({
    action: selected.stage === "D" ? "choose-databases" : "choose-query",
    session: selected.index,
    rows: [...picked],
    generation: page.generation,
    source: inputSource(),
  }),
);
$("create-query").addEventListener("submit", (event) => {
  event.preventDefault();
  editorKey = "";
  action({
    action: "create-query",
    session: selected.index,
    ...fields(event.target),
  });
});
$("create-query").elements.name.addEventListener("input", (event) => {
  $("create-query").elements.directory.value =
    `${data.libraries.query_workspaces}/${event.target.value}`;
});
$("save-query").addEventListener("submit", (event) => {
  event.preventDefault();
  action({
    action: "edit-query",
    session: selected.index,
    ...fields(event.target),
  });
});
$("work").addEventListener("submit", (event) => {
  event.preventDefault();
  action({
    action: "work",
    session: selected.index,
    stage: selected.stage,
    ...fields(event.target),
  });
});
$("compare").addEventListener("click", () => {
  showDetail("comparison");
  action({ action: "compare", sessions: [...chosen] });
});
initializeDisclosure("collapse-system", "system-body", "MRVA system summary");
initializeDisclosure("collapse-workflow", "workflow-body", "workflow commands");
initializeDisclosure(
  "collapse-infrastructure",
  "infrastructure-body",
  "infrastructure commands",
);
initializeDisclosure("collapse-sessions", "sessions-body", "sessions");
initializeDisclosure("collapse-comparison", "comparison-body", "comparison");
if (new URLSearchParams(location.search).get("view") !== "assistant") {
  presentation = initializePresentation();
  initializeSplitter();
  window.addEventListener("bench-presentation-change", () => {
    if (data) {
      renderGrid();
      disableControls();
    }
  });
  reload();
  setInterval(refreshSystem, 1500);
}
