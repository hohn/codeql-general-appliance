import assert from "node:assert/strict";

const [endpoint, helpURL, injectionURL] = process.argv.slice(2);
const socket = new WebSocket(endpoint);
const pending = new Map();
const network = [];
const exceptions = [];
let sequence = 0;
socket.addEventListener("message", event => {
  const message = JSON.parse(event.data);
  if (message.method === "Network.requestWillBeSent") {
    network.push(message.params.request.url);
  }
  if (message.method === "Runtime.exceptionThrown") {
    exceptions.push(message.params.exceptionDetails);
  }
  if (!pending.has(message.id)) return;
  const [resolve, reject] = pending.get(message.id);
  pending.delete(message.id);
  if (message.error) reject(new Error(message.error.message));
  else resolve(message.result);
});
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, {once: true});
  socket.addEventListener("error", reject, {once: true});
});

function send(method, params = {}, sessionId) {
  const id = ++sequence;
  return new Promise((resolve, reject) => {
    pending.set(id, [resolve, reject]);
    socket.send(JSON.stringify({id, method, params, sessionId}));
  });
}

async function evaluate(session, expression) {
  const result = await send("Runtime.evaluate", {
    expression, returnByValue: true, awaitPromise: true,
  }, session);
  assert.equal(result.exceptionDetails, undefined, JSON.stringify(result.exceptionDetails));
  return result.result.value;
}

async function until(check, description) {
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    const result = await check();
    if (result) return result;
    await new Promise(resolve => setTimeout(resolve, 30));
  }
  throw new Error(`Timed out: ${description}`);
}

async function clickAnchor(origin, ref, count = 1) {
  const point = await evaluate(origin, `(() => {
    const badge = [...document.querySelectorAll(".cga-vid")].find(node => node.dataset.vid === ${JSON.stringify(ref)});
    badge.scrollIntoView({block: "center"});
    const box = badge.getBoundingClientRect();
    return {x: box.left + box.width / 2, y: box.top + box.height / 2};
  })()`);
  await send("Page.bringToFront", {}, origin);
  for (let clickCount = 1; clickCount <= count; clickCount++) {
    await send("Input.dispatchMouseEvent", {
      type: "mousePressed", ...point, button: "left", clickCount,
    }, origin);
    await send("Input.dispatchMouseEvent", {
      type: "mouseReleased", ...point, button: "left", clickCount,
    }, origin);
  }
}

async function inspector(origin, ref) {
  const previous = (await send("Target.getTargets")).targetInfos.map(target => target.targetId);
  await clickAnchor(origin, ref, 2);
  const target = await until(async () =>
    (await send("Target.getTargets")).targetInfos.find(candidate =>
      !previous.includes(candidate.targetId) && candidate.title.includes("CGA help inspector")),
  `offline inspector for ${ref}`);
  const {sessionId} = await send("Target.attachToTarget", {targetId: target.targetId, flatten: true});
  await until(() => evaluate(sessionId, `!!document.querySelector("#context")?.value`),
    "pinned inspector context");
  return {targetId: target.targetId, sessionId};
}

const {targetId} = await send("Target.createTarget", {url: "about:blank"});
const {sessionId} = await send("Target.attachToTarget", {targetId, flatten: true});
await send("Runtime.enable", {}, sessionId);
await send("Network.enable", {}, sessionId);
await send("Network.setBlockedURLs", {urls: ["http://*", "https://*"]}, sessionId);
await send("Emulation.setDeviceMetricsOverride", {
  width: 1400, height: 900, deviceScaleFactor: 1, mobile: false,
}, sessionId);
await send("Page.navigate", {url: helpURL}, sessionId);
await until(() => evaluate(sessionId,
  `document.querySelector('#start-tree .tree-item[aria-current="page"]')?.dataset.command === "cga help overview"`),
"offline help initialized");

assert.equal(await evaluate(sessionId, "location.protocol"), "file:");
assert.equal(await evaluate(sessionId,
  "document.querySelector('#top-title').textContent"), "cga help overview");
assert.deepEqual(await evaluate(sessionId,
  `[...document.querySelectorAll('#top-help h3')].map(heading => heading.textContent).filter(text => ["Overview", "Running"].includes(text))`),
["Overview", "Running"]);
assert.deepEqual(await evaluate(sessionId,
  `[...document.querySelectorAll('.outline > h2, .outline > details > summary')].map(heading => heading.textContent)`),
["Start here", "LLM start here", "Task groups", "Reference",
  "system tests", "Original write-ups"]);
assert.deepEqual(await evaluate(sessionId,
  `[...document.querySelectorAll('#command-tree, #system-tests, #tutorial-documents')].map(node => node.id)`),
["command-tree", "system-tests", "tutorial-documents"]);
assert.equal(await evaluate(sessionId,
  `document.querySelector("#start-outline #tutorial-documents")`), null);
assert.equal(await evaluate(sessionId,
  `document.querySelector("#system-tests").open`), false);
assert.equal(await evaluate(sessionId,
  `document.querySelector("#system-tests-tree a").checkVisibility()`), false);
await evaluate(sessionId, `document.querySelector("#system-tests > summary").focus()`);
await send("Input.dispatchKeyEvent", {
  type: "keyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, text: "\r",
}, sessionId);
await send("Input.dispatchKeyEvent", {
  type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13,
}, sessionId);
assert.equal(await evaluate(sessionId,
  `document.querySelector("#system-tests").open`), true);
assert.equal(await evaluate(sessionId,
  `document.querySelector("#system-tests-tree a").checkVisibility()`), true);
const systemTestsLink = await evaluate(sessionId, `(() => {
  const link = document.querySelector("#system-tests-tree a");
  return {href: link.href, target: link.target, rel: link.rel};
})()`);
assert.ok(systemTestsLink.href.endsWith("/cga/system-tests/README.html"));
assert.equal(systemTestsLink.target, "_blank");
assert.equal(systemTestsLink.rel, "noopener");
const beforeSystemTests = (await send("Target.getTargets")).targetInfos.map(target => target.targetId);
await evaluate(sessionId, `document.querySelector("#system-tests-tree a").click()`);
const systemTests = await until(async () =>
  (await send("Target.getTargets")).targetInfos.find(target =>
    !beforeSystemTests.includes(target.targetId) && target.url === systemTestsLink.href),
"system tests opened separately");
assert.equal(await evaluate(sessionId,
  `document.querySelector("#top-title").textContent`), "cga help overview");
await send("Target.closeTarget", {targetId: systemTests.targetId});
await evaluate(sessionId, `document.querySelector("#system-tests > summary").click()`);
assert.equal(await evaluate(sessionId,
  `document.querySelector("#system-tests").open`), false);
assert.deepEqual(await evaluate(sessionId,
  `[...document.querySelectorAll('#start-tree .tree-item')].slice(0, 7).map(entry => entry.textContent)`),
["Visual overview", "Reference manual", "CGA overview", "getting started",
 "bash example -- sqlite tutorial", "sample 05", "single-user MRVA flow"]);
await evaluate(sessionId,
  `document.querySelector('#start-tree [data-command="cga help getting-started"]').click()`);
assert.equal(await evaluate(sessionId,
  `document.querySelector("#top-title").textContent`), "cga help getting-started");
await evaluate(sessionId,
  `document.querySelector('#start-tree [data-command="cga help bash-tutorial-sql"]').click()`);
assert.equal(await evaluate(sessionId,
  `document.querySelector("#top-title").textContent`), "cga help bash-tutorial-sql");
await evaluate(sessionId,
  `document.querySelector('#top-help [data-command="cga help bash-tutorial-sql mrva"]').click()`);
assert.equal(await evaluate(sessionId,
  `document.querySelector("#bottom-title").textContent`), "cga help bash-tutorial-sql mrva");
assert.ok(await evaluate(sessionId,
  `document.querySelector("#bottom-help").textContent.includes("cga mr run --name sqlite-injection")`));
assert.equal(await evaluate(sessionId,
  `document.querySelectorAll("#bottom-help .shell-command").length`), 0);
await until(() => evaluate(sessionId,
  `!!document.querySelector('.cga-vid[data-vid=":nrs"]')`), "help anchor initialization");
assert.deepEqual(await evaluate(sessionId, `(() => {
  const badge = document.querySelector('.cga-vid[data-vid=":nrs"]');
  const box = badge.getBoundingClientRect();
  return {compact: box.width > 0 && box.width < 32 && box.height > 0 && box.height < 20,
    symbol: getComputedStyle(badge.querySelector(".cga-vid-symbol"), "::before").content,
    name: badge.getAttribute("aria-label"), text: badge.textContent,
    splitter: document.querySelector("#pane-divider .cga-vid")};
})()`), {compact: true, symbol: '"⚓"', name: "Copy :nrs; double-click to inspect CGA element",
  text: "", splitter: null});
await evaluate(sessionId, `window.referenceCopies = [];
  Object.defineProperty(navigator, "clipboard", {configurable: true,
    value: {writeText: async text => { window.referenceCopies.push(text); }}});
`);
const beforeCopy = (await send("Target.getTargets")).targetInfos.length;
await clickAnchor(sessionId, ":nrs");
await until(() => evaluate(sessionId, `window.referenceCopies.at(-1) === ":nrs"`), "copied short reference");
assert.equal((await send("Target.getTargets")).targetInfos.length, beforeCopy);
assert.equal(await evaluate(sessionId, `document.querySelector("#start-outline").open`), true);
assert.equal(await evaluate(sessionId, `document.querySelector("#top-title").textContent`), "cga help bash-tutorial-sql");
const sectionRef = ":vy8,help,bash-tutorial-sql,mrva,section,walkthrough";
const firstInspector = await inspector(sessionId, sectionRef);
const frozen = await evaluate(firstInspector.sessionId, `document.querySelector("#context").value`);
const snapshot = JSON.parse(frozen);
assert.equal(snapshot.reference, sectionRef);
assert.equal(snapshot.help.command, "cga help bash-tutorial-sql mrva");
assert.equal(snapshot.help.sections.length, 1);
assert.match(snapshot.help.sections[0].text, /cga mr run --name sqlite-injection/);
assert.equal(snapshot.generation, await evaluate(sessionId,
  `JSON.parse(document.querySelector("#help-data").textContent).references.generation`));
assert.ok(snapshot.qualified_ref.startsWith("cga://help?"));
assert.ok(snapshot.relations.some(relation => relation.reference === ":vy8,help,bash-tutorial-sql,mrva"));
assert.equal(await evaluate(firstInspector.sessionId,
  `document.querySelector("#terminal")`), null);
assert.equal(await evaluate(firstInspector.sessionId,
  `document.body.style.getPropertyValue("--vid-color")`),
await evaluate(sessionId, `document.querySelector('[data-vid="${sectionRef}"]').style.getPropertyValue("--vid-color")`));
await evaluate(firstInspector.sessionId, `Object.defineProperty(navigator, "clipboard", {
  configurable: true, value: {writeText: async text => { window.copiedContext = text; }}});
  document.querySelector(".terminal-actions button").click();
`);
await until(() => evaluate(firstInspector.sessionId,
  `window.copiedContext === document.querySelector("#context").value`), "copied pinned LLM context");
await evaluate(firstInspector.sessionId, `Object.defineProperty(navigator, "clipboard", {
  configurable: true, value: undefined});
  document.querySelectorAll(".terminal-actions button")[1].click();
`);
await until(() => evaluate(firstInspector.sessionId,
  `document.querySelector("#error").textContent.includes("manual copying")`), "link clipboard failure is explicit");
assert.equal(await evaluate(firstInspector.sessionId, `document.querySelector("#context").value`), frozen);
assert.equal(await evaluate(firstInspector.sessionId, `document.activeElement.value`), snapshot.link);
assert.match(await evaluate(sessionId, `(() => {
  const ref = new URL(${JSON.stringify(snapshot.qualified_ref)});
  ref.searchParams.set("document", "file:///other/help.html");
  try { CGAVIDConfig.openInspector({ref: ref.href, color: 0}); }
  catch (error) { return error.message; }
})()`), /different help document/);
await evaluate(sessionId, `Object.defineProperty(navigator, "clipboard", {
  configurable: true, value: undefined});`);
const secondInspector = await inspector(sessionId, ":nrs");
assert.ok(await evaluate(sessionId,
  `document.querySelector(".cga-vid-error").textContent.includes("clipboard access is unavailable")`));
assert.equal(await evaluate(sessionId, `document.querySelector("#start-outline").open`), true);
assert.equal(await evaluate(sessionId, `document.querySelector("#bottom-title").textContent`),
  "cga help bash-tutorial-sql mrva");
await evaluate(sessionId,
  `document.querySelector('#start-tree [data-command="cga help bench-intro"]').click()`);
assert.equal(await evaluate(firstInspector.sessionId, `document.querySelector("#context").value`), frozen);
await send("Target.closeTarget", {targetId: secondInspector.targetId});
await until(() => evaluate(sessionId,
  `!document.querySelector('.cga-vid[data-vid=":nrs"]').classList.contains("cga-vid-active")`),
  "closed inspector removes origin highlight");
assert.equal(await evaluate(firstInspector.sessionId, `document.querySelector("#context").value`), frozen);
await send("Target.closeTarget", {targetId: firstInspector.targetId});
await evaluate(sessionId, `location.hash = ${JSON.stringify("vid=" + encodeURIComponent(sectionRef) + "&at=" + snapshot.generation)}`);
await until(() => evaluate(sessionId,
  `document.querySelector("#top-title").textContent === "cga help bash-tutorial-sql mrva"
    && document.activeElement.dataset.vid === ${JSON.stringify(sectionRef)}`), "help reference deep link");
await evaluate(sessionId, `location.hash = "vid=:nrs&at=missing"`);
await until(() => evaluate(sessionId,
  `document.querySelector("#status").textContent.includes("snapshot is not retained")`), "stale snapshot rejected");
await evaluate(sessionId, `location.hash = ""`);
for (const [name, chapter, text] of [
  ["mrva-flow", "run", "mrva-flow.sh"],
  ["bench-intro", "sessions", "cga bench"],
  ["shell-workflow", "apply", "cga mr"],
  ["two-user-standalone", "run", "./12-bob-submit.sh"],
  ["two-user-workflow", "run", "./12-bob-submit.sh"],
  ["zlib-study", "mrva", "./90-submit.sh"],
]) {
  await evaluate(sessionId,
    `document.querySelector('#start-tree [data-command="cga help ${name}"]').click()`);
  assert.equal(await evaluate(sessionId,
    `document.querySelector("#top-title").textContent`), `cga help ${name}`);
  await evaluate(sessionId,
    `document.querySelector('#top-help [data-command="cga help ${name} ${chapter}"]').click()`);
  assert.equal(await evaluate(sessionId,
    `document.querySelector("#bottom-title").textContent`), `cga help ${name} ${chapter}`);
  assert.ok(await evaluate(sessionId,
    `document.querySelector("#bottom-help").textContent.includes(${JSON.stringify(text)})`),
  `${name} ${chapter} preserves its source text`);
  assert.equal(await evaluate(sessionId,
    `document.querySelectorAll("#bottom-help .shell-command").length`), 0);
}
await evaluate(sessionId, `document.querySelector("#start-outline > summary").click()`);
assert.equal(await evaluate(sessionId,
  `document.querySelector("#start-outline").open`), false);
assert.equal(await evaluate(sessionId,
  `document.querySelector("#start-tree .tree-item").checkVisibility()`), false);
await evaluate(sessionId, `document.querySelector("#start-outline > summary").click()`);
await evaluate(sessionId, `document.querySelector("#llm-start-outline > summary").focus()`);
await send("Input.dispatchKeyEvent", {
  type: "keyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, text: "\r",
}, sessionId);
await send("Input.dispatchKeyEvent", {
  type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13,
}, sessionId);
assert.equal(await evaluate(sessionId,
  `document.querySelector("#llm-start-outline").open`), false);
await evaluate(sessionId, `document.querySelector("#llm-start-outline > summary").click()`);
assert.equal(await evaluate(sessionId,
  `document.querySelector("#llm-start-tree a").textContent`), "LLM exploration guide");
await evaluate(sessionId,
  `document.querySelector('#llm-start-tree [data-command="cga llm context"]').click()`);
assert.equal(await evaluate(sessionId,
  `document.querySelector("#top-title").textContent`), "cga llm context");
await evaluate(sessionId,
  `document.querySelector('#top-help [data-command="cga llm context unified"]').click()`);
assert.equal(await evaluate(sessionId,
  `document.querySelector("#bottom-title").textContent`), "cga llm context unified");
const documentLink = await evaluate(sessionId, `(() => {
  const link = document.querySelector('#document-tree a[href$="cga/cgaassist/README.html"]');
  return {href: link.href, target: link.target, rel: link.rel, title: link.title,
    overflow: getComputedStyle(link).textOverflow, wrap: getComputedStyle(link).whiteSpace};
})()`);
assert.ok(documentLink.href.endsWith("/cga/cgaassist/README.html"));
assert.equal(documentLink.target, "_blank");
assert.equal(documentLink.rel, "noopener");
assert.match(documentLink.title, /bash example -- sqlite tutorial.*Original linear write-up/s);
assert.equal(documentLink.overflow, "ellipsis");
assert.equal(documentLink.wrap, "nowrap");
const beforeLink = (await send("Target.getTargets")).targetInfos.map(target => target.targetId);
assert.equal(await evaluate(sessionId,
  `document.querySelector("#tutorial-documents").open`), false);
await evaluate(sessionId,
  `document.querySelector("#tutorial-documents > summary").click()`);
assert.equal(await evaluate(sessionId,
  `document.querySelector("#tutorial-documents").parentElement.classList.contains("outline")`), true);
assert.equal(await evaluate(sessionId,
  `document.querySelector("#document-tree a").checkVisibility()`), true);
assert.equal(await evaluate(sessionId,
  `document.querySelectorAll("#document-tree a").length`), 8);
const bookLink = await evaluate(sessionId, `(() => {
  const link = document.querySelector('#document-tree a[href$="docs/book/index.html"]');
  return {href: link.href, label: link.textContent, target: link.target, rel: link.rel};
})()`);
assert.equal(bookLink.label, "Reference manual");
assert.equal(bookLink.target, "_blank");
assert.equal(bookLink.rel, "noopener");
await evaluate(sessionId,
  `document.querySelector('#document-tree a[href$="cga/cgaassist/README.html"]').click()`);
const tutorial = await until(async () =>
  (await send("Target.getTargets")).targetInfos.find(target =>
    !beforeLink.includes(target.targetId) && target.url === documentLink.href),
"tutorial opened separately");
assert.equal(await evaluate(sessionId,
  `document.querySelector("#bottom-title").textContent`), "cga llm context unified");
await send("Target.closeTarget", {targetId: tutorial.targetId});
await send("Runtime.evaluate", {
  expression: `document.querySelector('#document-tree a[href$="docs/book/index.html"]').click()`,
  userGesture: true,
}, sessionId);
const book = await until(async () =>
  (await send("Target.getTargets")).targetInfos.find(target =>
    !beforeLink.includes(target.targetId) && target.url === bookLink.href),
"book opened separately");
await send("Target.closeTarget", {targetId: book.targetId});
await evaluate(sessionId,
  `document.querySelector('#start-tree [data-command="cga help sample 05"]').click()`);
assert.ok(await evaluate(sessionId,
  `document.querySelector("#top-help").textContent.includes('five fixed database')`));
await evaluate(sessionId,
  `document.querySelector('#top-help a[data-command="cga help sample 05 00"]').click()`);
assert.equal(await evaluate(sessionId,
  "document.querySelector('#bottom-title').textContent"), "cga help sample 05 00");
assert.ok(await evaluate(sessionId,
  `document.querySelector("#bottom-help").textContent.includes('mkdir ')`));
await evaluate(sessionId, `
  document.querySelector('#command-tree [data-command="cga"]').click();
  document.querySelector("#command-tree details").open = true;
`);
assert.equal(await evaluate(sessionId, "document.querySelector('#top-title').textContent"), "cga");
assert.equal(await evaluate(sessionId,
  `document.querySelectorAll('#command-tree .tree-item[data-command="cga view"]').length`), 1);
const outlineLabels = await evaluate(sessionId,
  `[...document.querySelectorAll('#command-tree > li > details > ul > li .tree-item')].map(button => button.textContent)`);
assert.ok(outlineLabels.length > 30);
assert.deepEqual(outlineLabels, [...outlineLabels].sort());
assert.equal(await evaluate(sessionId,
  `document.querySelector('#command-tree [data-command="cga"]').textContent`), "cga index");
await evaluate(sessionId, `document.querySelector("#command-tree summary").click()`);
assert.equal(await evaluate(sessionId,
  `document.querySelector("#command-tree details").open`), false);
assert.equal(await evaluate(sessionId,
  `document.querySelector('#command-tree [data-command="cga init"]').checkVisibility()`), false);
await evaluate(sessionId, `document.querySelector('#command-tree [data-command="cga"]').click()`);
assert.equal(await evaluate(sessionId, "document.querySelector('#top-title').textContent"), "cga");
assert.equal(await evaluate(sessionId,
  `document.querySelector("#command-tree details").open`), true);
await evaluate(sessionId, `document.querySelector("#command-tree summary").click()`);
await evaluate(sessionId, `document.querySelector("#command-tree summary").focus()`);
await send("Input.dispatchKeyEvent", {
  type: "keyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, text: "\r",
}, sessionId);
await send("Input.dispatchKeyEvent", {
  type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13,
}, sessionId);
assert.equal(await evaluate(sessionId,
  `document.querySelector("#command-tree details").open`), true);
assert.deepEqual(await evaluate(sessionId,
  `[...document.querySelectorAll('#task-tree summary')].map(node => node.textContent)`),
["Create databases", "Write and prepare queries", "Apply queries", "Review results"]);
await evaluate(sessionId, `document.querySelector("#collapse-all").click()`);
assert.equal(await evaluate(sessionId,
  `document.querySelectorAll(".outline details[open]").length`), 0);
assert.equal(await evaluate(sessionId, "document.querySelector('#top-title').textContent"), "cga");
assert.equal(await evaluate(sessionId,
  `document.querySelector("#collapse-all").title`), "Collapse all");
await evaluate(sessionId,
  `document.querySelectorAll(".outline details").forEach(details => { details.open = true; })`);
await evaluate(sessionId,
  `document.querySelector('#task-tree [data-command="cga ql"]').click()`);
assert.equal(await evaluate(sessionId, "document.querySelector('#top-title').textContent"), "cga ql");
assert.equal(await evaluate(sessionId,
  `document.querySelectorAll('#task-tree [data-command="cga ql"][aria-current="page"]').length`), 2);
await evaluate(sessionId, `document.querySelector('#command-tree [data-command="cga"]').click()`);
await evaluate(sessionId, `document.querySelector("#command-tree details").open = true`);
const layout = await evaluate(sessionId, `(() => {
  const header = document.querySelector("header").getBoundingClientRect();
  const tree = document.querySelector(".outline").getBoundingClientRect();
  const top = document.querySelector("#top-help").getBoundingClientRect();
  const bottom = document.querySelector("#bottom-help").getBoundingClientRect();
  return {header: header.toJSON(), tree: tree.toJSON(), top: top.toJSON(), bottom: bottom.toJSON()};
})()`);
assert.ok(layout.header.bottom <= layout.tree.top);
assert.ok(layout.tree.right <= layout.top.left);
assert.ok(layout.top.bottom < layout.bottom.top);

await evaluate(sessionId,
  `document.querySelector('#top-help a[data-command="cga init"]').click()`);
assert.equal(await evaluate(sessionId, "document.querySelector('#top-title').textContent"), "cga");
assert.equal(await evaluate(sessionId,
  "document.querySelector('#bottom-title').textContent"), "cga init");
assert.equal(await evaluate(sessionId,
  "document.querySelectorAll('#bottom-help a').length"), 0);

await evaluate(sessionId,
  `document.querySelector('#command-tree [data-command="cga chain"]').click()`);
assert.equal(await evaluate(sessionId,
  "document.querySelector('#top-title').textContent"), "cga chain");
assert.match(await evaluate(sessionId,
  "document.querySelector('#bottom-title').textContent"), /No subcommand/);
await evaluate(sessionId,
  `document.querySelector('#top-help a[data-command="cga chain start"]').click()`);
assert.equal(await evaluate(sessionId,
  "document.querySelector('#bottom-title').textContent"), "cga chain start");

await evaluate(sessionId,
  `document.querySelector('#command-tree [data-command="cga llm"]').click();
   document.querySelector('#top-help a[data-command="cga llm context"]').click()`);
assert.equal(await evaluate(sessionId,
  "document.querySelector('#bottom-title').textContent"), "cga llm context");
assert.deepEqual(await evaluate(sessionId,
  `[...document.querySelectorAll('#bottom-help .shell-command input')].map(input => input.value)`),
["cga llm context bench -h", "cga llm context unified -h"]);
assert.equal(await evaluate(sessionId,
  "document.querySelectorAll('#bottom-help a').length"), 0);
await evaluate(sessionId, `Object.defineProperty(navigator, "clipboard", {value: undefined, configurable: true});
  document.querySelector("#bottom-help .shell-command button").click()`);
assert.match(await evaluate(sessionId,
  "document.querySelector('#status').textContent"), /selected for manual copying/);
assert.equal(await evaluate(sessionId, "document.activeElement.value"), "cga llm context bench -h");

const scroll = await evaluate(sessionId, `(() => {
  document.querySelector('#command-tree [data-command="cga"]').click();
  const top = document.querySelector("#top-help");
  top.scrollTop = 180;
  document.querySelector('#top-help a[data-command="cga bench"]').click();
  const before = top.scrollTop;
  const bottom = document.querySelector("#bottom-help");
  bottom.scrollTop = 150;
  return {before, after: top.scrollTop, bottom: bottom.scrollTop, window: window.scrollY};
})()`);
assert.ok(scroll.before > 0);
assert.equal(scroll.before, scroll.after);
assert.ok(scroll.bottom > 0);
assert.equal(scroll.window, 0);

async function search(query, regex = false) {
  await evaluate(sessionId, `
    document.querySelector("#search-query").value = ${JSON.stringify(query)};
    document.querySelector("#search-regex").checked = ${regex};
    document.querySelector('#help-search button[type="submit"]').click();
  `);
  return evaluate(sessionId,
    `[...document.querySelectorAll('#command-tree .search-match')].map(button => button.dataset.command)`);
}

await evaluate(sessionId, `document.querySelector("#collapse-all").click()`);
assert.ok((await search("relative filesystem store paths")).includes("cga init"));
assert.equal(await evaluate(sessionId,
  `document.querySelector("#command-tree details").open`), true);
assert.equal(await evaluate(sessionId,
  `document.querySelectorAll("#task-tree details[open]").length`), 0);
await evaluate(sessionId,
  `document.querySelector('#command-tree [data-command="cga init"]').click()`);
assert.equal(await evaluate(sessionId, "document.querySelector('#top-title').textContent"), "cga init");
assert.match(await evaluate(sessionId,
  "document.querySelector('#top-help mark').textContent"), /relative filesystem store paths/i);
assert.deepEqual(await search("^cga chain start$"), []);
await evaluate(sessionId, `
  document.querySelector("#search-regex").checked = true;
  document.querySelector("#search-regex").dispatchEvent(new Event("change"));
`);
assert.equal(await evaluate(sessionId,
  `document.querySelectorAll("#command-tree .search-match").length`), 0);
assert.deepEqual(await search("^cga chain start$", true), ["cga chain"]);
await evaluate(sessionId, `document.querySelector('#command-tree [data-command="cga chain"]').click()`);
assert.equal(await evaluate(sessionId, "document.querySelector('#top-title').textContent"), "cga chain");
assert.equal(await evaluate(sessionId,
  `document.querySelector('#top-help [data-command="cga chain start"]').classList.contains("search-match")`), true);
await evaluate(sessionId, `document.querySelector('#top-help [data-command="cga chain start"]').click()`);
assert.equal(await evaluate(sessionId, "document.querySelector('#bottom-title').textContent"), "cga chain start");
assert.ok((await search("[-h]")).includes("cga init"));
await search("[", true);
assert.match(await evaluate(sessionId,
  "document.querySelector('#search-status').textContent"), /Invalid regular expression/);
assert.equal(await evaluate(sessionId,
  "document.querySelector('#search-query').getAttribute('aria-invalid')"), "true");
assert.deepEqual(await search("no-such-help-7934"), []);
assert.equal(await evaluate(sessionId,
  "document.querySelector('#search-status').textContent"), "0 matching index entries.");
assert.ok((await search("^", true)).length > 30);
await search("");
assert.equal(await evaluate(sessionId, "document.querySelector('#search-status').hidden"), true);
assert.equal(await evaluate(sessionId, "document.querySelectorAll('mark').length"), 0);
await evaluate(sessionId, `
  document.querySelector("#search-query").value = "CGA_OBJECT_STORE";
  document.querySelector("#search-query").dispatchEvent(new Event("input"));
`);
assert.equal(await evaluate(sessionId,
  "document.querySelectorAll('#command-tree .search-match').length"), 0);
await evaluate(sessionId, `document.querySelector('#help-search button[type="submit"]').click()`);
assert.ok(await evaluate(sessionId, "document.querySelectorAll('#command-tree .search-match').length > 0"));
await search("");

const beforeResize = await evaluate(sessionId,
  'Number(document.querySelector("#pane-divider").getAttribute("aria-valuenow"))');
await evaluate(sessionId, 'document.querySelector("#pane-divider").focus()');
await send("Input.dispatchKeyEvent", {
  type: "keyDown", key: "ArrowDown", code: "ArrowDown", windowsVirtualKeyCode: 40,
}, sessionId);
const afterKeyboard = await evaluate(sessionId,
  'Number(document.querySelector("#pane-divider").getAttribute("aria-valuenow"))');
assert.ok(afterKeyboard > beforeResize);
const point = await evaluate(sessionId, `(() => {
  const box = document.querySelector("#pane-divider").getBoundingClientRect();
  return {x: box.left + box.width / 2, y: box.top + box.height / 2};
})()`);
await send("Input.dispatchMouseEvent", {type: "mouseMoved", ...point}, sessionId);
await send("Input.dispatchMouseEvent", {
  type: "mousePressed", ...point, button: "left", buttons: 1, clickCount: 1,
}, sessionId);
await send("Input.dispatchMouseEvent", {
  type: "mouseMoved", x: point.x, y: point.y + 50, button: "left", buttons: 1,
}, sessionId);
await send("Input.dispatchMouseEvent", {
  type: "mouseReleased", x: point.x, y: point.y + 50, button: "left", buttons: 0, clickCount: 1,
}, sessionId);
const afterPointer = await evaluate(sessionId,
  'Number(document.querySelector("#pane-divider").getAttribute("aria-valuenow"))');
assert.ok(afterPointer > afterKeyboard, JSON.stringify({
  point, afterKeyboard, afterPointer,
}));

await send("Emulation.setDeviceMetricsOverride", {
  width: 600, height: 500, deviceScaleFactor: 1, mobile: false,
}, sessionId);
await until(() => evaluate(sessionId, "innerWidth === 600"), "resized viewport");
await until(() => evaluate(sessionId,
  `[...document.querySelectorAll(".pane")].every(pane => pane.getBoundingClientRect().height >= 110)`),
"responsive pane minimum sizes");
const resized = await evaluate(sessionId, `(() => {
  const panes = [...document.querySelectorAll(".pane")].map(pane => pane.getBoundingClientRect());
  return {panes: panes.map(pane => pane.toJSON()), width: innerWidth,
    documentWidth: document.documentElement.scrollWidth};
})()`);
assert.ok(resized.panes.every(pane => pane.height >= 110 && pane.width > 0)
  && resized.documentWidth <= resized.width, JSON.stringify(resized));

await send("Page.navigate", {url: injectionURL}, sessionId);
await until(() => evaluate(sessionId,
  `document.querySelector("#top-help")?.textContent.includes("window.helpInjected")`),
"escaped help text rendered");
assert.equal(await evaluate(sessionId, "typeof window.helpInjected"), "undefined");
assert.equal(await evaluate(sessionId, "document.querySelectorAll('img').length"), 0);
assert.deepEqual(await search("window.helpInjected"), ["cga"]);
assert.equal(await evaluate(sessionId, "typeof window.helpInjected"), "undefined");
assert.equal(await evaluate(sessionId, "document.querySelectorAll('img').length"), 0);
assert.deepEqual(network.filter(url => /^https?:/.test(url)), []);
assert.deepEqual(exceptions, []);
await send("Target.closeTarget", {targetId});
socket.close();
