import assert from "node:assert/strict";

const [endpoint, url, catalogue, library, directory, preparationURL, nativeEditor] =
  process.argv.slice(2);
const socket = new WebSocket(endpoint);
const pending = new Map();
const popupLoads = new Map();
let sequence = 0;
let loaded;
socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) {
    const [resolve, reject] = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) reject(new Error(message.error.message));
    else resolve(message.result);
  }
  if (message.method === "Page.loadEventFired") {
    if (message.sessionId) popupLoads.get(message.sessionId)?.();
    else loaded?.();
  }
});
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});
function send(method, params = {}, sessionId) {
  const id = ++sequence;
  return new Promise((resolve, reject) => {
    pending.set(id, [resolve, reject]);
    socket.send(JSON.stringify({ id, method, params, sessionId }));
  });
}
await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", {
  width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false,
});
const load = new Promise((resolve) => {
  loaded = resolve;
});
await send("Page.navigate", { url: preparationURL });
await load;
const preparation = await send("Runtime.evaluate", {
  awaitPromise: true,
  returnByValue: true,
  expression: `(async () => {
    async function until(predicate) {
      const deadline = Date.now() + 10000;
      while (!predicate()) {
        if (Date.now() > deadline) throw new Error("Preparation timed out: " + predicate.toString() + "; " + document.querySelector("#error").textContent);
        await new Promise(resolve => setTimeout(resolve, 25));
      }
    }
    await until(() => data && !busy);
    const appleDefault = document.body.dataset.presentation === "apple" &&
      !document.querySelector("#bench-outline").hidden &&
      document.querySelector("#selection-panel").contains(document.querySelector("#grid")) &&
      !document.querySelector("#detail-placeholder").hidden;
    const bounds = selector => document.querySelector(selector).getBoundingClientRect();
    const left = bounds("#bench-outline"), upper = bounds("#selection-panel"), lower = bounds("#detail-panel");
    const threePaneLayout = left.right < upper.left && upper.left === lower.left &&
      upper.bottom < lower.top && left.top === upper.top && Math.abs(left.bottom - lower.bottom) < 1;
    const toolbarAligned = Math.abs(bounds("#header-content").left - upper.left) < 1 &&
      getComputedStyle(document.querySelector("#header-sidebar")).backgroundColor ===
      getComputedStyle(document.querySelector("#bench-outline")).backgroundColor;
    const sidebarSurfaceContinuous =
      getComputedStyle(document.querySelector("#workflow-splitter")).backgroundColor ===
      getComputedStyle(document.querySelector("#header-sidebar")).backgroundColor &&
      Math.abs(bounds("#header-sidebar").right - bounds("#workflow-splitter").right) < 1;
    const reloadButton = document.querySelector("#reload");
    const quietToolbar = [...document.querySelectorAll("#reload, .header-menu > summary")].every(control => {
      const style = getComputedStyle(control), box = control.getBoundingClientRect();
      return style.borderWidth === "0px" && style.backgroundColor === "rgba(0, 0, 0, 0)" &&
        Math.abs(box.top - bounds("#reload").top) < 1 && box.height === bounds("#reload").height;
    }) && reloadButton.getAttribute("aria-label") === "Reload" &&
      getComputedStyle(reloadButton.querySelector(".reload-label")).display === "none" &&
      reloadButton.querySelector("svg").getClientRects().length > 0;
    const outlineLabels = [...document.querySelectorAll("[data-outline-topic]")].every(control =>
      control.title && getComputedStyle(control).whiteSpace === "nowrap" &&
      getComputedStyle(control).textOverflow === "ellipsis");
    const originalFetch = window.fetch;
    let mutations = 0;
    window.fetch = (path, options) => {
      if (path === "api/action") ++mutations;
      return originalFetch(path, options);
    };
    const chooseTopic = key => document.querySelector('[data-outline-topic="' + key + '"]').click();
    chooseTopic("system");
    const summaryInP2 = document.querySelector("#selection-panel").contains(document.querySelector("#system-summary")) &&
      document.querySelector(".system-panel").getClientRects().length > 0;
    chooseTopic("workflow");
    chooseTopic("infrastructure");
    chooseTopic("setup");
    chooseTopic("maintenance");
    chooseTopic("command-check");
    const commandSelectedWithoutRunning = mutations === 0 &&
      document.querySelector('[data-phase="check"]').getClientRects().length > 0 &&
      document.querySelector('[data-phase="setup"]').getClientRects().length === 0 &&
      document.querySelector("#selection-title").textContent === "Check services";
    chooseTopic("comparison");
    const comparisonNavigationOnly = mutations === 0 &&
      document.querySelector("#selection-panel").contains(document.querySelector("#compare")) &&
      !document.querySelector("#detail-placeholder").hidden;
    chooseTopic("sessions");
    const systemRow = document.querySelector('[data-outline-topic="sysview"]');
    const systemViewSibling = systemRow.closest("li").parentElement.id === "outline-infrastructure" &&
      !document.querySelector('[data-outline-topic="command-view"]') &&
      document.querySelector("#show-infrastructure").getClientRects().length === 0;
    const sessionPanel = document.querySelector("#sessions-card");
    const experimentBeforeSystem = JSON.stringify(data.experiment);
    chooseTopic("sysview");
    await until(() => document.querySelector("#sysview-frame").dataset.loaded === "true");
    const systemViewInP3 = mutations === 0 &&
      !document.querySelector("#sysview-detail").hidden &&
      document.querySelector("#address").textContent === "Detail: MRVA system view" &&
      document.querySelector("#sysview-frame").src === new URL(systemSnapshot.url, location.href).href &&
      document.querySelector("#sysview-error").textContent === "" &&
      getComputedStyle(document.querySelector("#sysview-frame")).filter === "none";
    const systemViewPreservesP2 = document.querySelector("#selection-title").textContent === "Sessions" &&
      document.querySelector("#selection-panel").contains(sessionPanel) && !sessionPanel.hidden &&
      JSON.stringify(data.experiment) === experimentBeforeSystem;
    const trackingFetch = window.fetch;
    window.fetch = async (path, options) => path === "api/sysview"
      ? new Response(JSON.stringify({available: false, error: "fixture offline", url: systemSnapshot.url}), {status: 503})
      : trackingFetch(path, options);
    await refreshSystem();
    const embeddedOffline = document.querySelector("#sysview-frame").hidden &&
      !document.querySelector("#sysview-frame").hasAttribute("src") &&
      document.querySelector("#sysview-error").textContent.includes("fixture offline") &&
      !sessionPanel.hidden;
    window.fetch = trackingFetch;
    await refreshSystem();
    await until(() => document.querySelector("#sysview-frame").dataset.loaded === "true");
    const embeddedRecovery = !document.querySelector("#sysview-frame").hidden &&
      document.querySelector("#sysview-error").textContent === "";
    const togglePane = document.querySelector("#toggle-outline");
    const paneWidth = bounds("#selection-panel").width;
    const originalFrameURL = document.querySelector("#sysview-frame").src;
    togglePane.focus();
    togglePane.click();
    const paneCollapsed = document.querySelector("#bench-outline").hidden &&
      document.querySelector("#workflow-splitter").hidden &&
      togglePane.getAttribute("aria-expanded") === "false" &&
      togglePane.getAttribute("aria-label") === "Show navigation" &&
      bounds("#selection-panel").width > paneWidth &&
      bounds("#detail-panel").width === bounds("#selection-panel").width;
    togglePane.click();
    const paneRestored = !document.querySelector("#bench-outline").hidden &&
      togglePane.getAttribute("aria-expanded") === "true" &&
      togglePane.getAttribute("aria-label") === "Hide navigation" &&
      Math.abs(bounds("#selection-panel").width - paneWidth) < 1 &&
      document.querySelector("#selection-title").textContent === "Sessions" &&
      document.querySelector("#sysview-frame").src === originalFrameURL &&
      document.querySelector("#address").textContent === "Detail: MRVA system view";
    const sessionRow = document.querySelector('[data-outline-topic="sessions"]');
    sessionRow.focus();
    sessionRow.dispatchEvent(new KeyboardEvent("keydown", {key: "ArrowDown", bubbles: true}));
    const keyboardNavigation = document.activeElement.dataset.outlineTopic === "comparison";
    const setupToggle = document.querySelector('[data-outline-toggle="setup"]');
    setupToggle.click();
    const outlineCollapses = document.querySelector("#outline-setup").hidden &&
      setupToggle.getAttribute("aria-expanded") === "false";
    setupToggle.click();
    const vertical = document.querySelector("#workflow-splitter");
    const oldWidth = Number(vertical.getAttribute("aria-valuenow"));
    vertical.dispatchEvent(new KeyboardEvent("keydown", {key: "ArrowRight", bubbles: true}));
    const outlineResize = Number(vertical.getAttribute("aria-valuenow")) > oldWidth;
    const toolbarTracksDivider = Math.abs(bounds("#header-content").left - bounds("#selection-panel").left) < 1;
    vertical.dispatchEvent(new KeyboardEvent("keydown", {key: "Home", bubbles: true}));
    const horizontal = document.querySelector("#detail-splitter");
    horizontal.dispatchEvent(new KeyboardEvent("keydown", {key: "ArrowDown", bubbles: true}));
    const detailResize = Number(horizontal.getAttribute("aria-valuenow")) > 48;
    horizontal.dispatchEvent(new KeyboardEvent("keydown", {key: "Home", bubbles: true}));
    const selectionColor = getComputedStyle(document.body).getPropertyValue("--mac-selection").trim();
    const grayscaleTheme = selectionColor === "#383838" &&
      getComputedStyle(document.body).color === "rgb(36, 36, 36)";
    window.fetch = originalFetch;
    const modeRequired = document.querySelector("#new-session button").disabled;
    const mode = document.querySelector("#mode-menu .header-menu-popup");
    document.querySelector("#mode-menu summary").click();
    await until(() => document.querySelector("#mode-menu").open);
    const modeMenuWorks = mode.getClientRects().length > 0 &&
      !document.querySelector("#sessions-body").contains(mode) &&
      document.querySelector("#sessions-body").textContent.includes("Mode menu") &&
      !mode.querySelector("select, form") &&
      mode.querySelectorAll(":scope > button[data-mode]").length === 2;
    mode.querySelector('[data-mode="database-changes"]').click();
    await until(() => data.experiment.mode === "database-changes" && !busy);
    const modeSelected = !document.querySelector("#mode-menu").open &&
      mode.querySelector('[data-mode="database-changes"]').getAttribute("aria-pressed") === "true" &&
      mode.querySelector('[data-mode="query-changes"]').getAttribute("aria-pressed") === "false";
    const databaseModeGuidance = document.querySelector("#mode-status").textContent.includes(
      "Session 1 (S1) is the reference. Query Q is fixed; the Database selection D is editable.") &&
      document.querySelector("#mode-guidance").textContent === "Experiment mode: Database changes (fixed queries).";
    document.querySelector("#mode-menu summary").click();
    document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape"}));
    const modeDismisses = !document.querySelector("#mode-menu").open &&
      document.activeElement === document.querySelector("#mode-menu summary");
    document.querySelector("#new-session").requestSubmit();
    await until(() => data.experiment.sessions.length === 1 && !busy);
    const modeLocked = [...mode.querySelectorAll("[data-mode]")].every(button => button.disabled);
    const variantNeedsFixedInput = document.querySelector("#new-session button").disabled;
    const rowGrid = document.querySelectorAll("#grid > tr[data-session]").length === 1 &&
      document.querySelectorAll("#grid-head th").length === 7 &&
      document.querySelector('#grid th[data-session="1"]').textContent === "S1 Reference" &&
      !document.querySelector("#session-status-legend").hidden;
    const emptyStatus = document.querySelector('#grid button[data-session="1"][data-stage="D"]:not([data-mutation])');
    const databaseStatus = data.experiment.sessions[0].D.status;
    const emptyCircle = emptyStatus.textContent === "\\u25cb" &&
      emptyStatus.getAttribute("aria-label").includes(databaseStatus) && emptyStatus.title.startsWith(databaseStatus);
    const jobStatus = data.experiment.sessions[0].J.status;
    data.experiment.sessions[0].J.status = "running";
    renderGrid();
    const runningStatus = document.querySelector('#grid button[data-session="1"][data-stage="J"]');
    const halfCircle = runningStatus.textContent === "\\u25d0" &&
      runningStatus.getAttribute("aria-label").includes("running") && runningStatus.title.startsWith("running");
    data.experiment.sessions[0].J.status = jobStatus;
    const originalSessions = data.experiment.sessions;
    data.experiment.sessions = Array.from({length: 6}, (_, index) => {
      const session = structuredClone(originalSessions[0]);
      session.index = index + 1;
      session.vid = ":f3a," + session.index;
      session.status = "complete";
      for (const stage of ["D", "Q", "J", "R"]) {
        session[stage].vid = session.vid + "," + stage;
        session[stage].status = "complete";
        session[stage].can_edit = session[stage].can_clone = false;
      }
      return session;
    });
    renderGrid();
    const sixCompactRows = document.querySelectorAll("#grid > tr[data-session]").length === 6 &&
      document.querySelector(".session-grid").getBoundingClientRect().width <=
        document.querySelector("#selection-body").clientWidth &&
      document.querySelectorAll("#grid button.status-button").length === 24 &&
      !document.querySelector('#grid button[data-mutation="advance"]');
    data.experiment.sessions = originalSessions;
    renderGrid();
    document.querySelector('#grid button[data-session="1"][data-stage="D"]').click();
    const cellInP3 = document.querySelector("#detail-panel").contains(document.querySelector("#cell-detail")) &&
      !document.querySelector("#detail-panel").hasAttribute("data-detail-empty") &&
      document.querySelector("#address").textContent.includes("1");
    chooseTopic("comparison");
    const retainedDetail = selected.index === 1 && selected.stage === "D" &&
      !document.querySelector("#cell-detail").hidden;
    chooseTopic("sessions");
    const databaseCatalogueOnly =
      !document.querySelector("#database-input-source").hidden &&
      document.querySelector("#query-input-source").hidden &&
      !document.querySelector("#database-input-source select") &&
      !document.querySelector("#user-database");
    const discovered = document.querySelector("#catalogue-options");
    await until(() => Array.from(discovered.options).some(option => option.value === ${JSON.stringify(catalogue)}));
    const catalogueHelp = document.querySelector("#catalogue-help").textContent;
    const discoveryItems = document.querySelectorAll("#catalogue-discovery-status > ul > li");
    const discoveryOutlineWorks =
      discoveryItems.length === 3 &&
      discoveryItems[0].textContent === catalogues.paths.length + " found." &&
      discoveryItems[1].firstChild.textContent === "Searched:" &&
      JSON.stringify(Array.from(discoveryItems[1].querySelectorAll("ul > li"), li => li.textContent)) === JSON.stringify(catalogues.roots) &&
      discoveryItems[2].textContent.includes("Hidden/dependency directories and directory symlinks are not scanned");
    const catalogue = document.querySelector("#load-catalogue");
    discovered.value = ${JSON.stringify(catalogue)};
    discovered.dispatchEvent(new Event("change"));
    const catalogueChoiceWorks = catalogue.elements.path.value === ${JSON.stringify(catalogue)};
    catalogue.elements.path.value += ".manual";
    catalogue.elements.path.dispatchEvent(new Event("input"));
    const manualCatalogueWorks = discovered.value === "";
    catalogue.elements.path.value = ${JSON.stringify(catalogue)};
    catalogue.requestSubmit();
    await until(() => data.experiment.sessions[0].libraries.databases_loaded && !busy);
    await until(() => document.querySelectorAll("#collection-rows tr").length === 1);
    const search = document.querySelector("#collection-search");
    search.elements.search.value = "%";
    search.requestSubmit();
    await until(() => page && page.total === 0);
    const literalSearchWorks = document.querySelectorAll("#collection-rows tr").length === 0;
    search.elements.search.value = "2.27";
    search.requestSubmit();
    await until(() => page && page.total === 1 && document.querySelectorAll("#collection-rows tr").length === 1);
    document.querySelector("#collection-rows input").click();
    document.querySelector("#use-selection").click();
    await until(() => data.experiment.sessions[0].D.status === "complete" && !busy);
    document.querySelector('#grid button[data-session="1"][data-stage="Q"]').click();
    const index = document.querySelector("#index-library");
    index.elements.directory.value = ${JSON.stringify(library)};
    index.requestSubmit();
    await until(() => data.experiment.sessions[0].libraries.queries_loaded && !busy);
    await until(() => document.querySelectorAll("#collection-rows tr").length === 1);
    document.querySelector("#collection-rows input").click();
    const copy = document.querySelector("#copy-query");
    copy.elements.directory.value = ${JSON.stringify(directory + "-copy")};
    copy.requestSubmit();
    await until(() => data.experiment.sessions[0].has_query_workspace && !busy);
    await until(() => document.querySelector("#save-query").elements.source.value.includes("Example"));
    const queryCopyWorks =
      inputSource() === "user" &&
      !document.querySelector("#query-editor").hidden &&
      data.experiment.sessions[0].Q.status !== "complete" &&
      !data.experiment.sessions[0].Q.cloned_from;
    chooseTopic("command-check");
    document.querySelector('[data-phase="check"]').click();
    await until(() => infrastructureRun?.status === "complete" && !busy);
    const explicitInfrastructureInP3 = document.querySelector("#address").textContent === "Detail: Check services" &&
      document.querySelector("#detail-panel").contains(document.querySelector("#infrastructure-detail")) &&
      document.querySelector("#infrastructure-detail").getClientRects().length > 0;
    chooseTopic("comparison");
    document.querySelector("#show-comparison").click();
    const comparisonInP3 = document.querySelector("#detail-panel").contains(document.querySelector("#comparison-detail")) &&
      document.querySelector("#comparison-detail").getClientRects().length > 0;
    chooseTopic("sessions");
    document.querySelector('[data-presentation-control][data-presentation="classic"]').click();
    const classicRestoresPanels = document.querySelector(".workflow-panel").contains(document.querySelector("#grid")) &&
      document.querySelector(".system-panel").parentElement === document.body;
    document.querySelector("#collapse-sessions").click();
    document.querySelector('[data-presentation-control][data-presentation="apple"]').click();
    const outlineOverridesClassicCollapse = document.querySelector("#sessions-body").getClientRects().length > 0;
    document.querySelector('[data-presentation-control][data-presentation="classic"]').click();
    const classicCollapseRetained = document.querySelector("#sessions-body").hidden;
    document.querySelector("#collapse-sessions").click();
    document.querySelector('[data-presentation-control][data-presentation="apple"]').click();
    return {appleDefault, threePaneLayout, toolbarAligned, sidebarSurfaceContinuous, toolbarTracksDivider, quietToolbar,
      outlineLabels, paneCollapsed, paneRestored, summaryInP2, commandSelectedWithoutRunning,
      systemViewSibling, systemViewInP3, systemViewPreservesP2, embeddedOffline, embeddedRecovery,
      comparisonNavigationOnly, keyboardNavigation, outlineCollapses, outlineResize, detailResize,
      grayscaleTheme, cellInP3, retainedDetail, explicitInfrastructureInP3, comparisonInP3,
      classicRestoresPanels, outlineOverridesClassicCollapse, classicCollapseRetained,
      modeRequired, modeMenuWorks, modeSelected, modeLocked, rowGrid, emptyCircle, halfCircle, sixCompactRows,
      databaseModeGuidance, modeDismisses,
      variantNeedsFixedInput, databaseCatalogueOnly,
      discoveryOutlineWorks, catalogueChoiceWorks, manualCatalogueWorks, literalSearchWorks,
      queryCopyWorks, catalogueHelp};
  })()`,
});
assert.equal(
  preparation.exceptionDetails,
  undefined,
  JSON.stringify(preparation.exceptionDetails),
);
for (const [key, value] of Object.entries(preparation.result.value)) {
  if (key !== "catalogueHelp") assert.equal(value, true, key);
}
assert.match(preparation.result.value.catalogueHelp, /SQLite files/);
assert.match(preparation.result.value.catalogueHelp, /metadata.sql/);
assert.doesNotMatch(
  preparation.result.value.catalogueHelp,
  /ask your assistant/,
);
for (const [selector, dx, dy] of [["#workflow-splitter", 30, 0], ["#detail-splitter", 0, 30]]) {
  const handle = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const element = document.querySelector(${JSON.stringify(selector)});
      const box = element.getBoundingClientRect();
      return {x: box.left + box.width / 2, y: box.top + box.height / 2,
        value: Number(element.getAttribute("aria-valuenow"))};
    })()`,
  });
  const {x, y, value} = handle.result.value;
  await send("Input.dispatchMouseEvent", {type: "mouseMoved", x, y});
  await send("Input.dispatchMouseEvent", {type: "mousePressed", x, y, button: "left", clickCount: 1});
  await send("Input.dispatchMouseEvent", {type: "mouseMoved", x: x + dx, y: y + dy, button: "left", buttons: 1});
  await send("Input.dispatchMouseEvent", {type: "mouseReleased", x: x + dx, y: y + dy, button: "left", clickCount: 1});
  const resized = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `Number(document.querySelector(${JSON.stringify(selector)}).getAttribute("aria-valuenow"))`,
  });
  assert.ok(resized.result.value > value, selector + " must respond to dragging");
  if (selector === "#workflow-splitter") {
    const aligned = await send("Runtime.evaluate", {
      returnByValue: true,
      expression: 'Math.abs(document.querySelector("#header-content").getBoundingClientRect().left - document.querySelector("#selection-panel").getBoundingClientRect().left) < 1',
    });
    assert.equal(aligned.result.value, true, "Toolbar boundary must track pointer resizing");
  }
}
await send("Emulation.setDeviceMetricsOverride", {
  width: 390, height: 844, deviceScaleFactor: 1, mobile: false,
});
const narrow = await send("Runtime.evaluate", {
  returnByValue: true, awaitPromise: true,
  expression: `(async () => {
    await new Promise(requestAnimationFrame);
    const outline = document.querySelector("#bench-outline").getBoundingClientRect();
    const upper = document.querySelector("#selection-panel").getBoundingClientRect();
    const lower = document.querySelector("#detail-panel").getBoundingClientRect();
    return {
      stacked: upper.top >= outline.bottom && lower.top >= upper.bottom,
      width: document.documentElement.scrollWidth,
      viewport: innerWidth,
      header: document.querySelector("header").getBoundingClientRect().width,
      toolbar: document.querySelector("#header-content").getBoundingClientRect().width,
    };
  })()`,
});
assert.ok(narrow.result.value.stacked && narrow.result.value.width <= narrow.result.value.viewport,
  "Narrow screens must stack panes without horizontal page overflow: " + JSON.stringify(narrow.result.value));
await send("Emulation.setDeviceMetricsOverride", {
  width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false,
});
const mainLoad = new Promise((resolve) => {
  loaded = resolve;
});
await send("Page.navigate", { url });
await mainLoad;
const appearance = await send("Runtime.evaluate", {
  awaitPromise: true, returnByValue: true,
  expression: `(async () => {
    const deadline = Date.now() + 10000;
    while (!data || busy) {
      if (Date.now() > deadline) throw new Error("Default appearance did not load");
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    const defaultApple = document.body.dataset.presentation === "apple";
    document.querySelector('#grid input[data-session="1"]').click();
    document.querySelector('[data-presentation-control][data-presentation="classic"]').click();
    const comparisonChoiceRetained = document.querySelector('#grid input[data-session="1"]').checked;
    document.querySelector('#grid input[data-session="1"]').click();
    return defaultApple && comparisonChoiceRetained && document.body.dataset.presentation === "classic" &&
      document.querySelector("#bench-outline").hidden &&
      document.querySelector(".workflow-panel").contains(document.querySelector("#grid")) &&
      document.querySelector(".system-panel").parentElement === document.body;
  })()`,
});
assert.equal(appearance.exceptionDetails, undefined, JSON.stringify(appearance.exceptionDetails));
assert.equal(appearance.result.value, true, "Classic layout must remain available");
const classicReload = new Promise(resolve => { loaded = resolve; });
await send("Page.reload");
await classicReload;
const persistedAppearance = await send("Runtime.evaluate", {
  returnByValue: true,
  expression: `document.body.dataset.presentation === "classic"`,
});
assert.equal(persistedAppearance.result.value, true, "Appearance must survive reload");
const assistant = await send("Runtime.evaluate", {
  awaitPromise: true, returnByValue: true, userGesture: true,
  expression: `(async () => {
    const before = await (await fetch("api/assistant", {
      method: "POST", headers: {"Content-Type": "application/json", "X-CGA-Bench": "1"},
      body: JSON.stringify({operation: "open"}),
    })).json();
    const control = document.querySelector("#collapse-assistant");
    const panel = document.querySelector(".assistant-panel");
    const viewMenu = document.querySelector("#view-menu");
    const modeMenu = document.querySelector("#mode-menu");
    const order = document.querySelector("#reload").closest(".cga-vid-control").nextElementSibling === viewMenu &&
      viewMenu.nextElementSibling === modeMenu;
    const reloadBounds = document.querySelector("#reload").getBoundingClientRect();
    const alignedMenus = [viewMenu, modeMenu].every(menu => {
      const bounds = menu.querySelector("summary").getBoundingClientRect();
      return Math.abs(bounds.top - reloadBounds.top) < 1 &&
        Math.abs(bounds.height - reloadBounds.height) < 1;
    });
    const mainOnly = panel.hidden && !document.querySelector(".xterm") &&
      !document.querySelector("#assistant-terminal") && !document.querySelector("#assistant-connect") &&
      !document.querySelector("#assistant-start") && !document.querySelector("#assistant-stop");
    viewMenu.querySelector("summary").click();
    await new Promise(resolve => setTimeout(resolve, 25));
    const viewMenuWorks = control.getClientRects().length > 0 &&
      viewMenu.contains(document.querySelector("#sysview-link")) &&
      !document.querySelector(".system-panel").contains(document.querySelector("#sysview-link"));
    const systemLink = document.querySelector("#sysview-link");
    const viewItemStyle = getComputedStyle(control);
    const sharedViewStyle = ["backgroundColor", "color", "borderWidth", "borderRadius",
      "padding", "font", "textDecorationLine"].every(property =>
        getComputedStyle(systemLink)[property] === viewItemStyle[property]);
    const simpleMenuRows = viewItemStyle.borderWidth === "0px" &&
      viewItemStyle.backgroundColor === "rgba(0, 0, 0, 0)" &&
      getComputedStyle(viewMenu.querySelector(".header-menu-popup")).borderRadius === "10px";
    const liveSystemLabel = systemLink.textContent.trim().replace(/\\s+/g, " ") === "live system";
    modeMenu.querySelector("summary").click();
    await new Promise(resolve => setTimeout(resolve, 25));
    const exclusiveMenus = !viewMenu.open && modeMenu.open;
    document.querySelector("h1").click();
    const outsideDismisses = !modeMenu.open;
    const queryModeGuidance = document.querySelector("#mode-status").textContent.includes(
      "Session 1 (S1) is the reference. Database selection D is fixed; the Query Q is editable.") &&
      document.querySelector("#mode-guidance").textContent === "Experiment mode: Query changes (fixed databases).";
    const setup = document.querySelector('[data-phase="setup"]');
    const maintenance = document.querySelector("#maintenance button");
    const groupedActions = setup.closest(".infrastructure-group")?.getAttribute("aria-labelledby") === "setup-heading" &&
      maintenance.closest(".infrastructure-group")?.getAttribute("aria-labelledby") === "maintenance-heading" &&
      !maintenance.closest("details") && maintenance.getClientRects().length > 0;
    const actionStyle = getComputedStyle(setup);
    const sharedActionStyle = ["#maintenance button", "#compare", "#show-comparison",
      "#use-selection", "#session-tab-F", "#mode-menu [data-mode]"].every(selector => {
      const style = getComputedStyle(document.querySelector(selector));
      return style.backgroundColor === actionStyle.backgroundColor &&
        style.borderWidth === "0px" && style.borderRadius === actionStyle.borderRadius &&
        style.fontFamily === actionStyle.fontFamily;
    });
    const addSessionStyle = getComputedStyle(document.querySelector("#new-session button"));
    const outlinedAddSession = addSessionStyle.borderWidth === "1px" &&
      addSessionStyle.borderStyle === "solid" &&
      addSessionStyle.borderRadius === actionStyle.borderRadius;
    const outlinedHeader = [...document.querySelectorAll("#reload, .header-menu > summary")].every(control => {
      const style = getComputedStyle(control);
      return style.border === addSessionStyle.border &&
        style.borderRadius === addSessionStyle.borderRadius;
    });
    const menuPanelStyle = getComputedStyle(viewMenu.querySelector(".header-menu-popup"));
    const shadowlessBoxes = [...document.querySelectorAll(
      ".header-menu-popup, section, .workflow-card, .infrastructure-group, .comparison-controls, .summary-card, .runtime-card, .detail-card, .session-evidence-panel",
    )].every(box => getComputedStyle(box).boxShadow === "none");
    const matchesSummaryPalette = menuPanelStyle.backgroundColor ===
      getComputedStyle(document.querySelector(".system-panel .summary-card")).backgroundColor;
    const sharedSubtreeStyle = [...document.querySelectorAll(".infrastructure-group, #comparison-body")].every(panel => {
      const style = getComputedStyle(panel);
      return style.backgroundColor === menuPanelStyle.backgroundColor &&
        style.borderRadius === menuPanelStyle.borderRadius &&
        style.boxShadow === menuPanelStyle.boxShadow &&
        style.fontFamily === menuPanelStyle.fontFamily;
    });
    const borderlessArrows = [...document.querySelectorAll(".disclosure-button")].every(
      button => getComputedStyle(button).borderWidth === "0px");
    const original = window.open;
    window.open = () => null;
    viewMenu.querySelector("summary").click();
    control.click();
    const blockedError = document.querySelector("#assistant-error").textContent.includes("Allow pop-ups") &&
      document.querySelector("#assistant-error").getClientRects().length > 0 && !viewMenu.open;
    window.open = (...args) => (window.testAssistantPopup = original(...args));
    viewMenu.querySelector("summary").click();
    control.click();
    window.open = original;
    return {id: before.id, order, alignedMenus, mainOnly, viewMenuWorks, sharedViewStyle, simpleMenuRows, liveSystemLabel, exclusiveMenus,
      outsideDismisses, queryModeGuidance, groupedActions, sharedActionStyle, outlinedAddSession, outlinedHeader, shadowlessBoxes, matchesSummaryPalette, sharedSubtreeStyle, borderlessArrows, blockedError};
  })()`,
});
assert.equal(assistant.exceptionDetails, undefined, JSON.stringify(assistant.exceptionDetails));
for (const [key, value] of Object.entries(assistant.result.value)) {
  if (key !== "id") assert.equal(value, true, key);
}

async function assistantTarget() {
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    const { targetInfos } = await send("Target.getTargets");
    const targets = targetInfos.filter((target) => target.type === "page" &&
      target.url === url + "/?view=assistant");
    assert.ok(targets.length <= 1, "View assistant must reuse its popup");
    if (targets.length) return targets[0];
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error("Assistant popup did not open");
}
async function assistantView(sessionId, text = "CGA_COPILOT_STUB_STARTED") {
  const result = await send("Runtime.evaluate", {
    awaitPromise: true, returnByValue: true,
    expression: `(async () => {
      const deadline = Date.now() + 10000;
      while (!document.querySelector("#assistant-terminal .xterm-rows")?.textContent.includes(${JSON.stringify(text)})) {
        if (Date.now() > deadline) throw new Error("Popup terminal timed out: " +
          document.querySelector("#assistant-error")?.textContent);
        await new Promise(resolve => setTimeout(resolve, 25));
      }
      const value = await (await fetch("api/assistant", {
        method: "POST", headers: {"Content-Type": "application/json", "X-CGA-Bench": "1"},
        body: JSON.stringify({operation: "open"}),
      })).json();
      if (!value.running) throw new Error("Popup did not attach to the running assistant");
      if (document.querySelector(".bench-workspace").getClientRects().length)
        throw new Error("Popup must not show the Bench workspace");
      for (const name of ["connect", "start", "stop"]) {
        if (!document.querySelector("#assistant-" + name)?.getClientRects().length)
          throw new Error("Popup lifecycle controls missing");
      }
      if (document.querySelector("#assistant-error").textContent)
        throw new Error(document.querySelector("#assistant-error").textContent);
      document.querySelector("#assistant-terminal .xterm-helper-textarea").focus();
      return value.id;
    })()`,
  }, sessionId);
  assert.equal(result.exceptionDetails, undefined, JSON.stringify(result.exceptionDetails));
  assert.equal(result.result.value, assistant.result.value.id);
}
const firstAssistantTarget = await assistantTarget();
const { sessionId: assistantSession } = await send("Target.attachToTarget", {
  targetId: firstAssistantTarget.targetId, flatten: true,
});
await assistantView(assistantSession);
await send("Runtime.evaluate", {
  userGesture: true,
  expression: `document.querySelector("#collapse-assistant").click()`,
});
assert.equal((await assistantTarget()).targetId, firstAssistantTarget.targetId);
await send("Input.insertText", { text: "browser-assistant-input" }, assistantSession);
await send("Input.dispatchKeyEvent", { type: "keyDown", key: "Enter", code: "Enter",
  windowsVirtualKeyCode: 13, text: "\r" }, assistantSession);
await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter",
  windowsVirtualKeyCode: 13 }, assistantSession);
await assistantView(assistantSession, "ASSISTANT_REPLY:browser-assistant-input");
await send("Page.enable", {}, assistantSession);
const assistantReload = new Promise((resolve) => { popupLoads.set(assistantSession, resolve); });
await send("Page.reload", {}, assistantSession);
await assistantReload;
await assistantView(assistantSession, "ASSISTANT_REPLY:browser-assistant-input");
await send("Target.closeTarget", { targetId: firstAssistantTarget.targetId });
await send("Runtime.evaluate", {
  userGesture: true, awaitPromise: true,
  expression: `(async () => {
    const deadline = Date.now() + 10000;
    while (!window.testAssistantPopup.closed) {
      if (Date.now() > deadline) throw new Error("Assistant popup did not close");
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    document.querySelector("#collapse-assistant").click();
  })()`,
});
const reopenedAssistant = await assistantTarget();
assert.notEqual(reopenedAssistant.targetId, firstAssistantTarget.targetId);
const { sessionId: reopenedSession } = await send("Target.attachToTarget", {
  targetId: reopenedAssistant.targetId, flatten: true,
});
await assistantView(reopenedSession, "ASSISTANT_REPLY:browser-assistant-input");
await send("Target.closeTarget", { targetId: reopenedAssistant.targetId });
const result = await send("Runtime.evaluate", {
  awaitPromise: true,
  returnByValue: true,
  userGesture: true,
  expression: `(async () => {
    async function until(predicate) {
      const deadline = Date.now() + 10000;
      while (!predicate()) {
        if (Date.now() > deadline) throw new Error("UI condition timed out: " + predicate.toString() + "; " + document.querySelector("#address").textContent + "; " + document.querySelector("#error").textContent);
        await new Promise(resolve => setTimeout(resolve, 25));
      }
    }
    const sessionCount = () => document.querySelectorAll("#grid-head th[data-session]").length;
    const cell = (session, stage) => document.querySelector(
      '#grid button[data-session="' + session + '"][data-stage="' + stage + '"]');
    await until(() => sessionCount() === 1);
    const workflow = document.querySelector('[aria-label="Workflow commands"]');
    const preparationInDetail =
      workflow.contains(document.querySelector("#new-session")) &&
      !workflow.contains(document.querySelector("#load-catalogue")) &&
      document.querySelector("#cell-detail").contains(document.querySelector("#load-catalogue")) &&
      document.querySelector("#cell-detail").contains(document.querySelector("#index-library")) &&
      !document.querySelector("#requirement").closest("#workspace") &&
      !document.querySelector("#artifact-summary").closest("#workspace");
    const transposedGrid =
      ['D', 'Q', 'J', 'R'].every(stage =>
        document.querySelectorAll('#grid tr[data-stage="' + stage + '"] button:not([data-mutation]):not(.cga-vid)').length === 1);
    const sessions = data.experiment.sessions;
    data.experiment.sessions = [];
    renderGrid();
    const emptyGridWorks = document.querySelector("#grid").textContent.includes("No sessions yet");
    data.experiment.sessions = sessions;
    renderGrid();
    document.querySelector("#collapse-system").click();
    await refreshSystem();
    const summaryCollapsed =
      document.querySelector("#system-body").hidden &&
      document.querySelector("#collapse-system").textContent === "\\u25b8" &&
      document.querySelector("#collapse-system").getAttribute("aria-expanded") === "false";
    document.querySelector("#collapse-system").click();
    const summaryExpanded = !document.querySelector("#system-body").hidden;
    const runtimeDetailsWork =
      document.querySelector("#system-detail").textContent.includes("bench-test") &&
      document.querySelector("#system-detail").textContent.includes('"succeeded":1') &&
      document.querySelector("#system-detail").textContent.includes('"working":1') &&
      document.querySelector("#system-detail").textContent.includes("pending spawns: 1");
    const originalFetch = window.fetch;
    const staleView = structuredClone(data);
    for (const session of staleView.experiment.sessions)
      for (const stage of ["D", "Q", "R"]) delete session[stage].items;
    window.fetch = async (path, options) => path === "api/view"
      ? new Response(JSON.stringify(staleView))
      : originalFetch(path, options);
    await reload();
    const staleServerErrorWorks =
      document.querySelector("#error").textContent.includes("Bench server is out of date") &&
      document.querySelector("#error").textContent.includes("cga bench stop") &&
      document.querySelector("#error").textContent.includes("Reloading the page is not enough");
    window.fetch = originalFetch;
    document.querySelector("#error").textContent = "";
    window.fetch = async (path, options) => path === "api/sysview"
      ? new Response(JSON.stringify({available: false, error: "test offline", url: "/sysview"}), {status: 503})
      : originalFetch(path, options);
    await refreshSystem();
    const summaryOfflineWorks =
      document.querySelector("#system-availability").textContent === "offline" &&
      document.querySelector("#system-summary").textContent.includes("test offline") &&
      document.querySelector("#system-detail").textContent === "";
    window.fetch = originalFetch;
    await refreshSystem();
    document.querySelector("#collapse-infrastructure").click();
    document.querySelector("#collapse-sessions").click();
    document.querySelector("#collapse-comparison").click();
    render();
    const subtopicsCollapsed =
      document.querySelector("#infrastructure-body").hidden &&
      document.querySelector("#sessions-body").hidden &&
      document.querySelector("#comparison-body").hidden &&
      document.querySelector("#collapse-infrastructure").getAttribute("aria-expanded") === "false" &&
      document.querySelector("#collapse-sessions").getAttribute("aria-expanded") === "false" &&
      document.querySelector("#collapse-comparison").getAttribute("aria-expanded") === "false" &&
      document.querySelector("#collapse-sessions").textContent === "\\u25b8" &&
      document.querySelector("#collapse-infrastructure").parentElement.querySelector("h3").getClientRects().length > 0;
    const infrastructureHeading =
      document.querySelector("#collapse-infrastructure").parentElement.querySelector("h3");
    const infrastructureHeaderWorks =
      infrastructureHeading.textContent === "Infrastructure" &&
      !infrastructureHeading.querySelector("button:not(.cga-vid)") &&
      document.querySelector("#infrastructure-body").contains(document.querySelector("#show-infrastructure"));
    document.querySelector("#collapse-workflow").click();
    document.querySelector("#collapse-workflow").click();
    const subtopicStateRetained =
      document.querySelector("#infrastructure-body").hidden &&
      document.querySelector("#sessions-body").hidden &&
      document.querySelector("#comparison-body").hidden;
    document.querySelector("#collapse-infrastructure").click();
    const subtopicsIndependent =
      !document.querySelector("#infrastructure-body").hidden &&
      document.querySelector("#sessions-body").hidden &&
      document.querySelector("#comparison-body").hidden;
    document.querySelector("#collapse-sessions").click();
    const subtopicsExpanded =
      !document.querySelector("#sessions-body").hidden &&
      document.querySelector("#collapse-sessions").getAttribute("aria-expanded") === "true" &&
      document.querySelector("#new-session").getClientRects().length > 0;
    document.querySelector("#collapse-comparison").click();
    const comparisonExpanded =
      !document.querySelector("#comparison-body").hidden &&
      document.querySelector("#collapse-comparison").getAttribute("aria-expanded") === "true" &&
      document.querySelector("#compare").getClientRects().length > 0;
    document.querySelector("#collapse-workflow").click();
    render();
    const workflowCollapsed =
      document.querySelector("#workflow-body").hidden &&
      document.querySelector("#collapse-workflow").getAttribute("aria-expanded") === "false";
    document.querySelector("#collapse-workflow").click();
    const sharedDetail =
      document.querySelector("#detail-panel").contains(document.querySelector("#cell-detail")) &&
      document.querySelector("#detail-panel").contains(document.querySelector("#infrastructure-detail")) &&
      document.querySelector("#detail-panel").contains(document.querySelector("#comparison-detail"));
    const splitter = document.querySelector("#workflow-splitter");
    const initialSplit = Number(splitter.getAttribute("aria-valuenow"));
    splitter.dispatchEvent(new KeyboardEvent("keydown", {key: "ArrowRight", bubbles: true}));
    const splitterWorks = Number(splitter.getAttribute("aria-valuenow")) > initialSplit;
    splitter.dispatchEvent(new KeyboardEvent("keydown", {key: "Home", bubbles: true}));
    const initial = document.querySelector("#grid").textContent;
    cell(1, "Q").click();
    const queryAddress = document.querySelector("#address").textContent;
    const newSession = document.querySelector("#new-session");
    const sessionFieldsHidden = newSession.querySelectorAll("input").length === 0;
    const firstSessionLabel = document.querySelector('#grid-head th[data-session="1"] > span').textContent;
    document.querySelector("#show-infrastructure").click();
    const infrastructureDetailWorks =
      !document.querySelector("#infrastructure-detail").hidden &&
      document.querySelector("#cell-detail").hidden;
    document.querySelector('[data-phase="check"]').click();
    await until(() => infrastructureRun?.status === "complete" && !busy);
    const infrastructureActionWorks =
      document.querySelector("#address").textContent === "Detail: Check services" &&
      document.querySelector("#infrastructure-action-status").textContent === "Check services: completed";
    document.querySelector("#show-infrastructure").click();
    render();
    const infrastructureOverviewAfterActionWorks =
      document.querySelector("#address").textContent === "Detail: Infrastructure" &&
      document.querySelector("#infrastructure-action-status").textContent === "Check services: completed";
    await infrastructure("build");
    const infrastructureErrorWorks =
      document.querySelector("#address").textContent === "Detail: Build MRVA services" &&
      infrastructureRun.status === "failed" &&
      document.querySelector("#infrastructure-error").textContent.length > 0 &&
      document.querySelector("#infrastructure-error").textContent === document.querySelector("#error").textContent;
    document.querySelector("#show-infrastructure").click();
    const infrastructureOverviewAfterErrorWorks =
      document.querySelector("#address").textContent === "Detail: Infrastructure" &&
      document.querySelector("#infrastructure-error").textContent === infrastructureRun.error;
    document.querySelector("#show-comparison").click();
    const comparisonDetailWorks =
      !document.querySelector("#comparison-detail").hidden &&
      document.querySelector("#infrastructure-detail").hidden;
    document.querySelector('#grid input[data-session="1"]').click();
    const comparisonWaitsForVariants =
      document.querySelector("#compare").disabled &&
      !document.querySelector("#comparison-detail").hidden &&
      !data.comparison &&
      document.querySelector('#grid input[data-session="1"]').checked;
    cell(1, "R").click();
    await until(() => resultPage?.total === 35 && !resultLoading);
    let evidenceInEveryStageWorks = true;
    for (const stage of ["D", "Q", "J", "R"]) {
      await selectCell(1, stage);
      const active = ["D", "Q", "R"].includes(stage) ? stage : "R";
      evidenceInEveryStageWorks &&=
        document.querySelector("#session-tab-" + active).getAttribute("aria-selected") === "true" &&
        !document.querySelector("#session-panel-" + active).hidden &&
        document.querySelectorAll("#session-evidence [role=tab]").length === 4 &&
        document.querySelector("#session-evidence").contains(document.querySelector("#session-panel-F"));
    }
    document.querySelector("#session-tab-D").click();
    const acceptedDatabasesWork =
      !document.querySelector("#session-panel-D").hidden &&
      document.querySelector("#session-panel-D").textContent.includes("acme/repo") &&
      document.querySelector("#session-panel-D h3 .cga-vid")?.dataset.vid === data.experiment.sessions[0].D.vid &&
      document.querySelector("#session-panel-D tbody .cga-vid")?.dataset.vid === data.experiment.sessions[0].D.children[0].ref &&
      document.querySelector("#session-panel-D tbody tr").textContent.includes(data.experiment.sessions[0].D.items[0].sha256);
    document.querySelector("#session-tab-Q").click();
    const acceptedQueriesWork =
      !document.querySelector("#session-panel-Q").hidden &&
      document.querySelector("#session-panel-D").hidden &&
      document.querySelector("#session-panel-Q tbody .cga-vid")?.dataset.vid === data.experiment.sessions[0].Q.vid + ",1" &&
      document.querySelector("#session-panel-Q").textContent.includes("cpp/test");
    document.querySelector("#session-tab-R").click();
    const resultSummaryWorks =
      document.querySelector("#session-panel-R h3 .cga-vid")?.dataset.vid === data.experiment.sessions[0].R.vid &&
      document.querySelector("#session-panel-R").textContent.includes("35 findings") &&
      document.querySelector("#session-panel-R tbody tr").textContent.includes("acme/repo-1") &&
      document.querySelector("#session-panel-R tbody tr").textContent.includes("35");
    document.querySelector("#session-tab-R").dispatchEvent(new KeyboardEvent("keydown", {key: "ArrowLeft", bubbles: true}));
    const tabArrowWorks = document.activeElement.id === "session-tab-Q" &&
      !document.querySelector("#session-panel-Q").hidden;
    document.querySelector("#session-tab-Q").dispatchEvent(new KeyboardEvent("keydown", {key: "Home", bubbles: true}));
    const tabHomeWorks = document.activeElement.id === "session-tab-D";
    document.querySelector("#session-tab-D").dispatchEvent(new KeyboardEvent("keydown", {key: "End", bubbles: true}));
    const evidenceKeyboardWorks = tabArrowWorks && tabHomeWorks &&
      document.activeElement.id === "session-tab-F" &&
      document.querySelector("#session-tab-F").tabIndex === 0 &&
      document.querySelector("#session-tab-D").tabIndex === -1 &&
      !document.querySelector("#session-panel-F").hidden;
    const compactPreviewsWork = ["D", "Q", "R"].every(stage => {
      const panel = document.querySelector("#session-panel-" + stage);
      return panel.querySelectorAll("tbody tr").length === 1 &&
        panel.querySelector(".session-preview-count").textContent.includes("Count: 1.") &&
        panel.querySelector("a").href.includes("/evidence?session=1&stage=" + stage);
    });
    const findingsPreviewWorks =
      document.querySelector("#session-tab-F").textContent === "Findings" &&
      document.querySelector("#result-status").textContent.includes("Count: 35.") &&
      document.querySelectorAll("#result-rows tr").length === 1 &&
      document.querySelector("#session-panel-F a").href.includes("/evidence?session=1&stage=F") &&
      !document.querySelector("#result-filters") &&
      !document.querySelector("#open-editor");
    const originalEvidenceOpen = window.open;
    window.open = () => null;
    document.querySelector("#session-panel-R a").click();
    const evidencePopupErrorWorks =
      document.querySelector("#session-evidence-error").textContent.includes("Allow pop-ups");
    window.open = originalEvidenceOpen;
    let editorPid;
    if (${nativeEditor === "yes"}) {
      const descriptor = await request("api/editor", {
        method: "POST",
        headers: {"Content-Type": "application/json", "X-CGA-Bench": "1"},
        body: JSON.stringify({session: 1}),
      });
      editorPid = descriptor.pid;
    }
    cell(1, "Q").click();
    cell(1, "R").click();
    cell(1, "Q").click();
    newSession.requestSubmit();
    await until(() => sessionCount() === 2 && !busy);
    const secondSessionLabel = document.querySelector('#grid-head th[data-session="2"] > span').textContent;
    cell(2, "D").click();
    const incompleteSessionEvidenceWorks =
      document.querySelector("#session-panel-D").textContent.includes("acme/repo") &&
      document.querySelector("#session-panel-Q").textContent.includes("No accepted queries yet.") &&
      document.querySelector("#session-panel-R").textContent.includes("No repository results yet.") &&
      !document.querySelector("#session-panel-R").textContent.includes("35 findings") &&
      document.querySelectorAll("#session-panel-F tbody tr").length === 0 &&
      !document.querySelector("#session-panel-F a");
    const fixedDatabaseReadOnly =
      document.querySelector("#workspace").hidden &&
      document.querySelector("#selection-workspace").hidden &&
      !document.querySelector("#clone-input").hidden &&
      document.querySelector("#input-role").textContent.includes("cloned from S1") &&
      !document.querySelector('#grid button[data-session="2"][data-stage="D"][data-mutation="edit"]') &&
      Boolean(document.querySelector('#grid button[data-session="2"][data-stage="Q"][data-mutation="edit"]'));
    document.querySelector("#clone-input").requestSubmit();
    await until(() => data.experiment.sessions[1].D.history.filter(entry => entry.text === "Cloned fixed input").length === 2 && !busy);
    const cloneActionWorks =
      data.experiment.sessions[1].Q.status !== "complete" &&
      data.experiment.sessions[1].J.status !== "complete" &&
      data.experiment.sessions[1].R.status !== "complete" &&
      !data.comparison;
    cell(2, "Q").click();
    const queryPreparationOnly =
      document.querySelector("#database-preparation").hidden &&
      !document.querySelector("#query-preparation").hidden &&
      !document.querySelector("#query-input-source").hidden &&
      document.querySelector("#database-input-source").hidden;
    const library = document.querySelector("#index-library");
    library.elements.directory.value = ${JSON.stringify(library)};
    library.requestSubmit();
    await until(() => data.experiment.sessions[1].libraries.queries_loaded && !busy);
    await until(() => document.querySelector("#collection-rows").textContent.includes("Example"));
    document.querySelector("#input-source").value = "user";
    document.querySelector("#input-source").dispatchEvent(new Event("change"));
    const create = document.querySelector("#create-query");
    create.elements.name.value = "MyQuery";
    create.elements.directory.value = ${JSON.stringify(directory)};
    create.requestSubmit();
    await until(() => data.experiment.sessions[1].has_query_workspace && !busy);
    await until(() => document.querySelector("#save-query").elements.source.value.includes("where false"));
    document.querySelector("#input-source").value = "list";
    document.querySelector("#input-source").dispatchEvent(new Event("change"));
    await until(() => document.querySelector("#collection-rows").textContent.includes("Example"));
    document.querySelector("#input-source").value = "user";
    document.querySelector("#input-source").dispatchEvent(new Event("change"));
    await until(() => document.querySelector("#collection-rows").textContent.includes("MyQuery"));
    cell(2, "D").click();
    const independentPreparationPaths =
      inputSource() === "list" &&
      document.querySelector("#query-input-source").hidden &&
      document.querySelector("#workspace").hidden &&
      !document.querySelector("#clone-input").hidden;
    cell(2, "Q").click();
    await until(() => document.querySelector("#collection-rows").textContent.includes("MyQuery"));
    const edit = document.querySelector("#save-query");
    edit.elements.source.value = edit.elements.source.value.replace("where false", "where true");
    edit.requestSubmit();
    await until(() => data.experiment.sessions[1].Q.history.some(entry => entry.text === "Saved query") && !busy);
    const work = document.querySelector("#work");
    work.elements.note.value = "Review the new detector";
    work.requestSubmit();
    await until(() => data.experiment.sessions[1].Q.history.some(entry => entry.text === "Review the new detector") && !busy);
    cell(2, "Q").click();
    await until(() => document.querySelector("#collection-rows").textContent.includes("MyQuery"));
    return {
      evidenceInEveryStageWorks, acceptedDatabasesWork, acceptedQueriesWork,
      resultSummaryWorks, evidenceKeyboardWorks, incompleteSessionEvidenceWorks,
      staleServerErrorWorks,
      compactPreviewsWork, findingsPreviewWorks, evidencePopupErrorWorks, editorPid,
      transposedGrid, summaryCollapsed, summaryExpanded, workflowCollapsed,
      subtopicsCollapsed, subtopicStateRetained, subtopicsIndependent, subtopicsExpanded, comparisonExpanded, infrastructureHeaderWorks,
      sharedDetail, splitterWorks, infrastructureDetailWorks, comparisonDetailWorks,
      runtimeDetailsWork, summaryOfflineWorks, infrastructureActionWorks,
      infrastructureOverviewAfterActionWorks, infrastructureOverviewAfterErrorWorks,
      infrastructureErrorWorks, comparisonWaitsForVariants,
      emptyGridWorks,
      initial, queryAddress, sessionFieldsHidden, firstSessionLabel, secondSessionLabel,
      fixedDatabaseReadOnly, cloneActionWorks,
      preparationInDetail, queryPreparationOnly,
      independentPreparationPaths, rows: sessionCount(),
      detailAddress: document.querySelector("#address").textContent,
      databaseStatus: data.experiment.sessions[1].D.status,
      error: document.querySelector("#error").textContent,
      commandsHidden: !document.querySelector("#tool") && !document.querySelector("#output") &&
        !document.body.textContent.includes("ql select"),
      panels: workflow.querySelectorAll(".workflow-card").length,
      editorVisible: !document.querySelector("#query-editor").hidden
    };
  })()`,
});
assert.equal(
  result.exceptionDetails,
  undefined,
  JSON.stringify(result.exceptionDetails),
);
assert.equal(result.result.value.rows, 2);
for (const key of [
  "transposedGrid",
  "summaryCollapsed",
  "summaryExpanded",
  "workflowCollapsed",
  "subtopicsCollapsed",
  "subtopicStateRetained",
  "subtopicsIndependent",
  "subtopicsExpanded",
  "comparisonExpanded",
  "infrastructureHeaderWorks",
  "sharedDetail",
  "splitterWorks",
  "infrastructureDetailWorks",
  "comparisonDetailWorks",
  "runtimeDetailsWork",
  "summaryOfflineWorks",
  "infrastructureActionWorks",
  "evidenceInEveryStageWorks",
  "compactPreviewsWork",
  "findingsPreviewWorks",
  "evidencePopupErrorWorks",
  "staleServerErrorWorks",
  "acceptedDatabasesWork",
  "acceptedQueriesWork",
  "resultSummaryWorks",
  "evidenceKeyboardWorks",
  "incompleteSessionEvidenceWorks",
  "infrastructureOverviewAfterActionWorks",
  "infrastructureOverviewAfterErrorWorks",
  "infrastructureErrorWorks",
  "comparisonWaitsForVariants",
  "fixedDatabaseReadOnly",
  "cloneActionWorks",
  "emptyGridWorks",
])
  assert.equal(result.result.value[key], true, key);
assert.equal(result.result.value.sessionFieldsHidden, true);
assert.equal(result.result.value.firstSessionLabel, "1 Reference (complete)");
assert.equal(result.result.value.secondSessionLabel, "2 (incomplete)");
assert.equal(result.result.value.queryAddress, "Detail: session 1, stage Q");
assert.equal(result.result.value.detailAddress, "Detail: session 2, stage Q");
assert.equal(result.result.value.preparationInDetail, true);
assert.equal(result.result.value.queryPreparationOnly, true);
assert.equal(result.result.value.independentPreparationPaths, true);
assert.equal(result.result.value.databaseStatus, "complete");
assert.equal(result.result.value.error, "");
assert.match(result.result.value.initial, /complete/);
assert.equal(result.result.value.commandsHidden, true);
assert.equal(result.result.value.panels, 3);
assert.equal(result.result.value.editorVisible, true);
const reloaded = new Promise((resolve) => {
  loaded = resolve;
});
await send("Page.reload");
await reloaded;
const restored = await send("Runtime.evaluate", {
  awaitPromise: true,
  returnByValue: true,
  expression: `(async () => {
    async function until(predicate) {
      const deadline = Date.now() + 10000;
      while (!predicate()) {
        if (Date.now() > deadline) throw new Error("Reloaded results did not become ready");
        await new Promise(resolve => setTimeout(resolve, 25));
      }
    }
    await until(() => document.querySelectorAll("#grid-head th[data-session]").length === 2);
    document.querySelector('#grid button[data-session="1"][data-stage="R"]').click();
    await until(() => resultPage?.total === 35 && !resultLoading);
    if (${nativeEditor !== "yes"}) return null;
    const descriptor = await request("api/editor", {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-CGA-Bench": "1"},
      body: JSON.stringify({session: 1}),
    });
    return descriptor.pid;
  })()`,
});
assert.equal(
  restored.exceptionDetails,
  undefined,
  JSON.stringify(restored.exceptionDetails),
);
if (nativeEditor === "yes") {
  assert.equal(restored.result.value, result.result.value.editorPid);
}
async function checkNativeEditor(findingsSession) {
  const launched = await send("Runtime.evaluate", {
    awaitPromise: true,
    returnByValue: true,
    userGesture: true,
    expression: `(async () => {
      document.querySelector("#open-editor").click();
      const deadline = Date.now() + 15000;
      while (document.querySelector("#open-editor").disabled) {
        if (Date.now() > deadline) throw new Error("VS Code editor launch timed out");
        await new Promise(resolve => setTimeout(resolve, 25));
      }
      return document.querySelector("#editor-status").textContent;
    })()`,
  }, findingsSession);
  assert.match(launched.result.value, /^VS Code:/);
  let popup;
  const deadline = Date.now() + 15000;
  while (!popup) {
    const { targetInfos } = await send("Target.getTargets");
    popup = targetInfos.find(
      (target) => target.type === "page" && target.url.includes("workspace="),
    );
    assert.ok(Date.now() < deadline, "VS Code popup must finish its authenticated redirect: " +
      JSON.stringify(targetInfos));
    if (!popup) await new Promise((resolve) => setTimeout(resolve, 100));
  }
  assert.ok(!popup.url.includes("password"), "password must not appear in the URL");
  const { sessionId } = await send("Target.attachToTarget", {
    targetId: popup.targetId,
    flatten: true,
  });
  const workbench = await send("Runtime.evaluate", {
    awaitPromise: true,
    returnByValue: true,
    expression: `(async () => {
      const deadline = Date.now() + 45000;
      while (!document.querySelector(".monaco-workbench")) {
        if (Date.now() > deadline) throw new Error("VS Code workbench did not load: " + document.body.innerText);
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      return {workspace: new URL(location.href).searchParams.get("workspace"), opener: window.opener};
    })()`,
  }, sessionId);
  assert.equal(workbench.exceptionDetails, undefined, JSON.stringify(workbench.exceptionDetails));
  assert.match(workbench.result.value.workspace, /session-1\/query\.code-workspace$/);
  assert.equal(workbench.result.value.opener, null);
  await send("Target.closeTarget", { targetId: popup.targetId });
}
for (const [stage, table] of [["D", "databases"], ["Q", "queries"], ["R", "result_summaries"], ["F", "sarif_results"]]) {
  const opened = await send("Runtime.evaluate", {
    userGesture: true, returnByValue: true,
    expression: `(() => {
      selectSessionTab(${JSON.stringify(stage)});
      document.querySelector("#session-panel-${stage} a").click();
      return document.querySelector("#session-evidence-error").textContent;
    })()`,
  });
  assert.equal(opened.exceptionDetails, undefined, JSON.stringify(opened.exceptionDetails));
  assert.equal(opened.result.value, "");
  const popupURL = url + "/evidence?session=1&stage=" + stage;
  let popup;
  const deadline = Date.now() + 10000;
  while (!popup) {
    const { targetInfos } = await send("Target.getTargets");
    popup = targetInfos.find(target => target.type === "page" && target.url === popupURL);
    assert.ok(Date.now() < deadline, "Evidence popup must load");
    if (!popup) await new Promise(resolve => setTimeout(resolve, 25));
  }
  const { sessionId } = await send("Target.attachToTarget", {
    targetId: popup.targetId, flatten: true,
  });
  const checked = await send("Runtime.evaluate", {
    awaitPromise: true, returnByValue: true,
    expression: `(async () => {
      async function until(predicate) {
        const deadline = Date.now() + 10000;
        while (!predicate()) {
          if (Date.now() > deadline) throw new Error("Evidence popup timed out: " + document.querySelector("#evidence-error")?.textContent);
          await new Promise(resolve => setTimeout(resolve, 25));
        }
      }
      await until(() => document.querySelector("#evidence-schema")?.textContent.includes(${JSON.stringify(table)}) &&
        !document.querySelector("#evidence-sql button").disabled);
      const form = document.querySelector("#evidence-sql");
      const initialRows = document.querySelectorAll("#evidence-rows tr").length;
      let findingsControlsWork = true, exactFiltersWork = true,
        literalFiltersWork = true, editorErrorsWork = true;
      if (${stage === "F"}) {
        const filters = document.querySelector("#result-filters"),
          editor = document.querySelector("#open-editor");
        findingsControlsWork = filters.getClientRects().length > 0 &&
          editor.getClientRects().length > 0 && !editor.disabled &&
          document.querySelector("#evidence-head").textContent.includes("Repository") &&
          document.querySelector("#evidence-rows").textContent.includes("acme/repo-1");
        filters.elements.rule_id.value = "rule-01";
        filters.requestSubmit();
        await until(() => !form.querySelector("button").disabled);
        exactFiltersWork = document.querySelectorAll("#evidence-rows tr").length === 1 &&
          document.querySelector("#evidence-rows").textContent.includes("rule-01");
        filters.elements.rule_id.value = "rule-%";
        filters.requestSubmit();
        await until(() => !form.querySelector("button").disabled);
        literalFiltersWork = document.querySelectorAll("#evidence-rows tr").length === 0 &&
          document.querySelector("#evidence-status").textContent.includes("No rows match");
        document.querySelector("#clear-result-filters").click();
        await until(() => !form.querySelector("button").disabled);
        const originalOpen = window.open, originalFetch = window.fetch;
        window.open = () => null;
        editor.click();
        const blockedError = document.querySelector("#editor-status").textContent.includes("Allow pop-ups");
        window.open = () => ({closed: false, close() { this.closed = true; }});
        window.fetch = async (path, options) => path === "api/editor"
          ? new Response(JSON.stringify({error: "code-server is missing; run cga cc install"}), {status: 400})
          : originalFetch(path, options);
        editor.click();
        await until(() => !editor.disabled);
        editorErrorsWork = blockedError &&
          document.querySelector("#editor-status").textContent.includes("cga cc install");
        window.open = originalOpen;
        window.fetch = originalFetch;
      }
      async function run(sql) {
        form.elements.sql.value = sql;
        form.requestSubmit();
        await until(() => !form.querySelector("button").disabled);
      }
      await run(${JSON.stringify(stage === "F"
        ? "SELECT rule_id FROM sarif_results ORDER BY rule_id"
        : `SELECT ordinal, range AS copy FROM ${table} CROSS JOIN range(35) ORDER BY copy`)});
      const firstPage = document.querySelectorAll("#evidence-rows tr").length === 30 &&
        !document.querySelector("#evidence-next").disabled;
      document.querySelector("#evidence-next").click();
      await until(() => !form.querySelector("button").disabled);
      const lastPage = document.querySelectorAll("#evidence-rows tr").length === 5 &&
        document.querySelector("#evidence-status").textContent.includes("31-35 of 35") &&
        document.querySelector("#evidence-next").disabled;
      document.querySelector("#evidence-previous").click();
      await until(() => !form.querySelector("button").disabled);
      const previousPage = document.querySelectorAll("#evidence-rows tr").length === 30;
      await run("WITH source AS (SELECT * FROM ${table}) SELECT count(*) AS n FROM source");
      const aggregation = document.querySelector("#evidence-head").textContent === "n" &&
        document.querySelector("#evidence-rows").textContent === ${JSON.stringify(stage === "F" ? "35" : "1")};
      await run("SELECT ${stage === "F" ? "rule_id" : "ordinal"} FROM ${table} WHERE false");
      const empty = document.querySelector("#evidence-head").textContent === ${JSON.stringify(stage === "F" ? "Rule ID" : "ordinal")} &&
        document.querySelectorAll("#evidence-rows tr").length === 0 &&
        !document.querySelector("#evidence-error").textContent;
      await run("DELETE FROM ${table}");
      const denied = document.querySelector("#evidence-error").textContent.includes("SELECT") &&
        document.querySelectorAll("#evidence-rows tr").length === 0 &&
        (${stage !== "F"} || !document.querySelector("#open-editor").disabled);
      document.querySelector("#evidence-reset").click();
      await until(() => !form.querySelector("button").disabled);
      const reset = document.querySelectorAll("#evidence-rows tr").length === ${stage === "F" ? 30 : 1} &&
        !document.querySelector("#evidence-error").textContent &&
        form.elements.sql.value.includes(${JSON.stringify(stage === "F" ? "FROM sarif_results" : `SELECT * FROM ${table}`)});
      return {initialRows, firstPage, lastPage, previousPage, aggregation, empty, denied, reset,
        findingsControlsWork, exactFiltersWork, literalFiltersWork, editorErrorsWork};
    })()`,
  }, sessionId);
  assert.equal(checked.exceptionDetails, undefined, JSON.stringify(checked.exceptionDetails));
  assert.equal(checked.result.value.initialRows, stage === "F" ? 30 : 1, stage);
  for (const [key, value] of Object.entries(checked.result.value))
    if (key !== "initialRows") assert.equal(value, true, stage + ": " + key);
  await send("Runtime.evaluate", {
    userGesture: true,
    expression: `document.querySelector("#session-panel-${stage} a").click()`,
  });
  const { targetInfos } = await send("Target.getTargets");
  const matches = targetInfos.filter(target => target.type === "page" && target.url === popupURL);
  assert.equal(matches.length, 1, "Evidence popup must be reused");
  assert.equal(matches[0].targetId, popup.targetId);
  if (stage === "F" && nativeEditor === "yes") await checkNativeEditor(sessionId);
  await send("Target.closeTarget", { targetId: popup.targetId });
}
socket.close();
