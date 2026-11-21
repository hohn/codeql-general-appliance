import assert from "node:assert/strict";

const [endpoint, benchURL, unifiedURL] = process.argv.slice(2);
const socket = new WebSocket(endpoint);
const pending = new Map();
let sequence = 0;
socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (!pending.has(message.id)) return;
  const [resolve, reject] = pending.get(message.id);
  pending.delete(message.id);
  if (message.error) reject(new Error(message.error.message));
  else resolve(message.result);
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
async function evaluate(session, expression, userGesture = false) {
  const value = await send("Runtime.evaluate", {
    expression, returnByValue: true, awaitPromise: true, userGesture,
  }, session);
  assert.equal(value.exceptionDetails, undefined, JSON.stringify(value.exceptionDetails));
  return value.result.value;
}
async function until(check, description) {
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    const result = await check();
    if (result) return result;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(`Timed out: ${description}`);
}
async function attach(targetId) {
  const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
  return sessionId;
}
async function targetList() {
  return (await send("Target.getTargets")).targetInfos;
}
async function clickReference(origin, selector, count) {
  await send("Page.bringToFront", {}, origin);
  const point = await evaluate(origin, `(() => {
    const element = document.querySelector(${JSON.stringify(selector)});
    element.scrollIntoView({block: "center", inline: "nearest"});
    const box = element.getBoundingClientRect();
    const x = box.left + box.width / 2, y = box.top + box.height / 2;
    const hit = document.elementFromPoint(x, y);
    return {x, y, theme: document.body.dataset.presentation,
      hit: hit?.outerHTML, hittable: hit?.closest(".cga-vid") === element, box: box.toJSON()};
  })()`);
  assert.ok(point.box.width > 0 && point.box.height > 0, JSON.stringify(point));
  assert.ok(point.hittable, JSON.stringify(point));
  await send("Input.dispatchMouseEvent", {type: "mouseMoved", x: point.x, y: point.y}, origin);
  for (let clickCount = 1; clickCount <= count; clickCount++) {
    await send("Input.dispatchMouseEvent", {
      type: "mousePressed", x: point.x, y: point.y, button: "left", clickCount,
    }, origin);
    await send("Input.dispatchMouseEvent", {
      type: "mouseReleased", x: point.x, y: point.y, button: "left", clickCount,
    }, origin);
  }
}
async function popup(origin, selector, previous) {
  await clickReference(origin, selector, 2);
  const context = await evaluate(origin, `({
    appearance: document.body.dataset.presentation || "unified",
    selector: ${JSON.stringify(selector)},
    errors: [...document.querySelectorAll(".cga-vid-error")].map(element => element.textContent),
  })`);
  const target = await until(async () => (await targetList()).find(
    (item) => item.type === "page" && item.url.includes("/vid?") && !previous.has(item.targetId)),
  "VID popup " + JSON.stringify(context));
  previous.add(target.targetId);
  const session = await attach(target.targetId);
  await until(() => evaluate(session, `document.querySelector("#terminal-status")?.textContent
    .startsWith("Separate shell")`), "popup xterm and owned shell");
  return { target, session };
}

for (const [url, ref, appearance] of [
  [benchURL, ":f3a,1,J", "apple"],
  [benchURL, ":f3a,1,J", "classic"],
  [unifiedURL, ":h7m,1", "classic"],
]) {
  await send("Browser.grantPermissions", {
    origin: new URL(url).origin,
    permissions: ["clipboardReadWrite", "clipboardSanitizedWrite"],
  });
  const { targetId } = await send("Target.createTarget", { url });
  const origin = await attach(targetId);
  await send("Emulation.setDeviceMetricsOverride", {
    width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false,
  }, origin);
  const selector = `.cga-vid[data-vid="${ref}"]`;
  await until(() => evaluate(origin,
    `!!document.querySelector(${JSON.stringify(selector)})`), "rendered dynamic VID");
  await until(() => evaluate(origin,
    `!!document.querySelector('.cga-vid[data-vid=":2kf"]')`), "static VID badges");
  if (url === benchURL && appearance === "classic") {
    await evaluate(origin, `document.querySelector('[data-presentation-control][data-presentation="classic"]').click()`);
  }
  const layout = await evaluate(origin, `(() => {
    const workspace = document.querySelector(".bench-workspace, .workspace");
    const apple = document.body.dataset.presentation === "apple";
    const workflow = apple ? document.querySelector("#bench-outline")
      : workspace.querySelector(":scope > .workflow-panel, :scope > aside");
    const detail = workspace.querySelector(":scope > #detail-panel, :scope > .right-column");
    const upper = apple ? document.querySelector("#selection-panel") : detail;
    const vertical = document.querySelector("#workflow-splitter");
    const horizontal = document.querySelector("#detail-splitter");
    CGAVID.attach(vertical, ":o3b");
    if (horizontal) CGAVID.attach(horizontal, ":r0x");
    const flowBox = workflow.getBoundingClientRect();
    const detailBox = detail.getBoundingClientRect();
    const splitterBox = vertical.getBoundingClientRect();
    const result = {
      noSplitterBadges: !document.querySelector(
        '.cga-vid[data-vid=":o3b"], .cga-vid[data-vid=":r0x"]'),
      detailOnRight: detailBox.left >= splitterBox.right &&
        splitterBox.left >= flowBox.right,
      sameRow: Math.abs(flowBox.top - upper.getBoundingClientRect().top) < 1,
      detailHasSpace: detailBox.width > 320,
    };
    vertical.dispatchEvent(new KeyboardEvent("keydown", {key: "ArrowRight", bubbles: true}));
    result.workflowResizes = workflow.getBoundingClientRect().width > flowBox.width;
    if (horizontal && !horizontal.hidden) {
      const panel = apple ? upper : detail.querySelector(".detail-panel");
      const transcript = apple ? detail : detail.querySelector(".terminal-panel");
      const panelBox = panel.getBoundingClientRect();
      const handleBox = horizontal.getBoundingClientRect();
      result.transcriptBelowDetail = transcript.getBoundingClientRect().top >= handleBox.bottom &&
        handleBox.top >= panelBox.bottom;
      horizontal.dispatchEvent(new KeyboardEvent("keydown", {key: "ArrowUp", bubbles: true}));
      const smaller = panel.getBoundingClientRect().height;
      horizontal.dispatchEvent(new KeyboardEvent("keydown", {key: "ArrowDown", bubbles: true}));
      result.detailResizes = panel.getBoundingClientRect().height > smaller;
    }
    return result;
  })()`);
  for (const [name, value] of Object.entries(layout)) {
    assert.equal(value, true, `${url}: ${name}`);
  }
  const presentation = await evaluate(origin, `(() => {
    const badge = document.querySelector(${JSON.stringify(selector)});
    const text = document.querySelector('.cga-vid[data-vid=":a9x"]');
    const reload = document.querySelector("#reload");
    const reloadStyle = getComputedStyle(reload);
    const box = badge.getBoundingClientRect();
    const heading = document.querySelector("#collapse-workflow, #collapse-all")?.nextElementSibling;
    const apple = document.body.dataset.presentation === "apple";
    return {
      compactAnchor: box.width > 0 && box.width < 32 && box.height > 0 && box.height < 20,
      noVisibleVID: badge.textContent === "" &&
        getComputedStyle(badge.querySelector(".cga-vid-symbol"), "::before").content === '"\\u2693"',
      namedVID: badge.title.includes(${JSON.stringify(ref)}) &&
        badge.getAttribute("aria-label").includes(${JSON.stringify(ref)}),
      textAnchorAppended: ${url === benchURL}
        ? apple ? text.previousElementSibling.dataset.outlineTopic === "workflow"
          : text.parentElement === heading && heading.lastElementChild === text
        : text.parentElement.id === "workflow-meta",
      headingAnchorAppended: !!heading?.querySelector(".cga-vid"),
      separateControl: reload.parentElement.classList.contains("cga-vid-control") &&
        reload.nextElementSibling?.dataset.vid === ":2kf" && !reload.querySelector("button"),
      consistentControlPadding: ${url === benchURL}
        ? [...document.querySelectorAll(".header-menu > summary")].every(summary =>
          getComputedStyle(summary).padding === reloadStyle.padding)
        : parseFloat(reloadStyle.paddingLeft) + parseFloat(reloadStyle.paddingRight) <
          parseFloat(reloadStyle.fontSize),
    };
  })()`);
  for (const [name, value] of Object.entries(presentation)) {
    assert.equal(value, true, `${url}: ${name}`);
  }
  const beforeSingleClicks = new Set((await targetList()).map((target) => target.targetId));
  for (const shortRef of [":a9x", ref]) {
    await clickReference(origin, `.cga-vid[data-vid="${shortRef}"]`, 1);
    assert.equal(await evaluate(origin, "navigator.clipboard.readText()", true), shortRef);
  }
  await new Promise((resolve) => setTimeout(resolve, 500));
  assert.equal((await targetList()).some((target) => target.url.includes("/vid?") &&
    !beforeSingleClicks.has(target.targetId)), false, "single-click must not open an inspector");
  const original = await evaluate(origin, `(async () => {
    const badge = document.querySelector(${JSON.stringify(selector)});
    const open = window.open;
    const write = navigator.clipboard.writeText;
    let attempted = "";
    window.open = (url) => { attempted = url; return null; };
    navigator.clipboard.writeText = async () => { throw new Error("test clipboard denied"); };
    try {
      badge.click();
      await new Promise(resolve => setTimeout(resolve, 0));
      const singleAttempt = attempted;
      badge.dispatchEvent(new MouseEvent("dblclick", {bubbles: true, cancelable: true, detail: 2}));
      await new Promise(resolve => setTimeout(resolve, 0));
      return {
        diagnostics: [...document.querySelectorAll(".cga-vid-error")].map(node => node.textContent).join("\\n"),
        attempted, singleAttempt,
      };
    } finally {
      window.open = open;
      navigator.clipboard.writeText = write;
    }
  })()`, true);
  assert.match(original.diagnostics, /Allow pop-ups/);
  assert.match(original.diagnostics, /Could not copy.*test clipboard denied/);
  assert.equal(original.singleAttempt, "");
  assert.match(original.attempted, /^vid\?/);
  // Clear injected diagnostics before measuring coordinates for real double-clicks.
  await evaluate(origin, `(async () => {
    document.querySelector(${JSON.stringify(selector)}).click();
    await new Promise(requestAnimationFrame);
  })()`, true);
  const previous = new Set((await targetList()).map((target) => target.targetId));
  const textPopup = await popup(origin, '.cga-vid[data-vid=":a9x"]', previous);
  await send("Page.bringToFront", {}, origin);
  assert.equal(await evaluate(origin, "navigator.clipboard.readText()", true), ":a9x");
  await send("Target.closeTarget", { targetId: textPopup.target.targetId });
  const first = await popup(origin, selector, previous);
  await send("Page.bringToFront", {}, origin);
  assert.equal(await evaluate(origin, "navigator.clipboard.readText()", true), ref);
  const second = await popup(origin, selector, previous);
  assert.equal(await evaluate(origin, "document.querySelectorAll('.cga-vid-error').length"), 0);
  assert.notEqual(first.target.targetId, second.target.targetId);
  const originColor = await evaluate(origin,
    `getComputedStyle(document.querySelector(${JSON.stringify(selector)})).backgroundColor`);
  const detail = await evaluate(first.session, `({
    reference: document.querySelector("#reference").textContent,
    full: document.querySelector("#qualified-reference").textContent,
    color: getComputedStyle(document.querySelector("#color-bar")).backgroundColor,
    xterm: !!document.querySelector(".xterm textarea"),
    facts: JSON.parse(document.querySelector("#facts").textContent).length,
    error: document.querySelector("#error").textContent,
  })`);
  assert.ok(detail.reference.startsWith(ref));
  assert.match(detail.full, /^cga:\/\/vid\?/);
  assert.ok(new URL(detail.full).searchParams.get("at").includes("~a"));
  assert.equal(detail.color, originColor);
  assert.equal(detail.xterm, true);
  assert.ok(detail.facts > 0);
  assert.equal(detail.error, "");

  await send("Page.bringToFront", {}, first.session);
  await evaluate(first.session, `document.querySelector(".xterm textarea").focus()`);
  await send("Input.insertText", { text: "printf '%s%s\\n' VID_ READY" }, first.session);
  await send("Input.dispatchKeyEvent", {
    type: "keyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, text: "\r",
  }, first.session);
  await send("Input.dispatchKeyEvent", {
    type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13,
  }, first.session);
  await until(() => evaluate(first.session,
    `document.querySelector(".xterm-rows").textContent.includes("VID_READY")`),
  "interactive xterm input/output");
  await evaluate(first.session, `document.querySelector("#insert").click()`);
  await until(() => evaluate(first.session,
    `document.querySelector(".xterm-rows").textContent.includes("copilot")`),
  "inserted Copilot command");
  assert.equal(await evaluate(second.session,
    `document.querySelector(".xterm-rows").textContent.includes("copilot")`), false);
  await evaluate(first.session, "window.close()");
  await until(async () => !(await targetList()).some(
    (item) => item.targetId === first.target.targetId), "first popup closed");
  assert.equal(await evaluate(second.session,
    `document.querySelector("#terminal-status").textContent.startsWith("Separate shell")`), true);
  assert.equal(await evaluate(origin,
    `document.querySelector(${JSON.stringify(selector)}).classList.contains("cga-vid-active")`), true);
  await evaluate(second.session, "window.close()");
  await until(() => evaluate(origin,
    `!document.querySelector(${JSON.stringify(selector)}).classList.contains("cga-vid-active")`),
  "origin highlight cleared after both popups close");
  await send("Target.closeTarget", { targetId });
}
socket.close();
