import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const [endpoint, overviewURL, legacyURL] = process.argv.slice(2);
const entryURLs = ["../index.html", "index.html"].map(
  (path) => new URL(path, overviewURL).href,
);
const commands = JSON.parse(readFileSync(0, "utf8"));
const socket = new WebSocket(endpoint);
const pending = new Map();
const requests = [];
const exceptions = [];
const targets = [];
let sequence = 0;
let session;

socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (message.method === "Network.requestWillBeSent") {
    requests.push(message.params.request.url);
  }
  if (message.method === "Network.webSocketCreated") {
    requests.push(message.params.url);
  }
  if (message.method === "Runtime.exceptionThrown") {
    exceptions.push(message.params.exceptionDetails);
  }
  const request = pending.get(message.id);
  if (!request) return;
  pending.delete(message.id);
  clearTimeout(request.timer);
  if (message.error) request.reject(new Error(message.error.message));
  else request.resolve(message.result);
});

await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});

function send(method, params = {}, sessionId = session) {
  const id = ++sequence;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      const detail =
        method === "Runtime.evaluate"
          ? `: ${params.expression.slice(0, 160)}`
          : "";
      reject(new Error(`Timed out: ${method}${detail}`));
    }, 10000);
    pending.set(id, { resolve, reject, timer });
    socket.send(
      JSON.stringify({
        id,
        method,
        params,
        ...(sessionId ? { sessionId } : {}),
      }),
    );
  });
}

async function evaluate(expression) {
  const result = await send("Runtime.evaluate", {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  assert.equal(
    result.exceptionDetails,
    undefined,
    JSON.stringify(result.exceptionDetails),
  );
  return result.result.value;
}

async function until(check, description) {
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    if (await check()) return;
    await new Promise((resolve) => setTimeout(resolve, 30));
  }
  throw new Error(`Timed out: ${description}`);
}

async function viewport(width, height = 900) {
  await send("Emulation.setDeviceMetricsOverride", {
    width,
    height,
    deviceScaleFactor: 1,
    mobile: false,
  });
}

async function createPage(javaScript = true) {
  const { targetId } = await send(
    "Target.createTarget",
    { url: "about:blank" },
    null,
  );
  targets.push(targetId);
  ({ sessionId: session } = await send(
    "Target.attachToTarget",
    { targetId, flatten: true },
    null,
  ));
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Network.setBlockedURLs", {
    urls: ["http://*", "https://*", "ws://*", "wss://*"],
  });
  await send("Emulation.setScriptExecutionDisabled", { value: !javaScript });
  await viewport(1440, 1000);
}

async function navigate(url, expectedURL = url) {
  await send("Page.navigate", { url });
  await until(
    () =>
      evaluate(
        `location.href === ${JSON.stringify(expectedURL)} &&
      document.readyState === "complete"`,
      ),
    `navigation to ${expectedURL}`,
  );
}

async function clickPoint(x, y) {
  await send("Input.dispatchMouseEvent", {
    type: "mousePressed",
    x,
    y,
    button: "left",
    clickCount: 1,
  });
  await send("Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x,
    y,
    button: "left",
    clickCount: 1,
  });
}

async function click(selector) {
  const point = await evaluate(`(() => {
    const element = document.querySelector(${JSON.stringify(selector)});
    if (!element) throw new Error("Missing element: " + ${JSON.stringify(selector)});
    element.scrollIntoView({block: "center", inline: "center"});
    const box = element.getBoundingClientRect();
    const x = box.left + box.width / 2, y = box.top + box.height / 2;
    return {x, y, hittable: element.contains(document.elementFromPoint(x, y))};
  })()`);
  assert.ok(point.hittable, `Cannot click ${selector}`);
  await clickPoint(point.x, point.y);
}

async function key(key, code, windowsVirtualKeyCode) {
  await send("Input.dispatchKeyEvent", {
    type: "keyDown",
    key,
    code,
    windowsVirtualKeyCode,
  });
  await send("Input.dispatchKeyEvent", {
    type: "keyUp",
    key,
    code,
    windowsVirtualKeyCode,
  });
}

async function openDoorway(id) {
  await click(`[data-doorway][href="#${id}"]`);
  assert.ok(
    await evaluate(
      'document.querySelector("#doorway:modal")?.querySelector("#doorway-title")?.checkVisibility()',
    ),
    `Missing doorway for ${id}`,
  );
}

async function copyCommand(label) {
  await evaluate("window.copiedCommand = undefined");
  const scope = (await evaluate('document.querySelector("#doorway").open'))
    ? "#doorway "
    : "";
  await click(`${scope}[data-copy][aria-label=${JSON.stringify(label)}]`);
  await until(
    () =>
      evaluate(`window.copiedCommand === ${JSON.stringify(commands[label])}`),
    `exact copied command: ${label}`,
  );
}

try {
  await createPage();
  await navigate(overviewURL);
  const visualStyle = `[
    getComputedStyle(document.body).fontFamily,
    getComputedStyle(document.documentElement).backgroundColor,
    getComputedStyle(document.querySelector("h2")).fontWeight,
    getComputedStyle(document.querySelector("code")).fontFamily
  ]`;
  const overviewStyle = await evaluate(visualStyle);
  assert.equal(await evaluate("location.protocol"), "file:");
  assert.equal(
    await evaluate(
      'document.querySelectorAll("input, select, textarea, form, iframe").length',
    ),
    0,
    "Keep the worked example free of configuration/execution controls",
  );
  const chapters = [
    "the-cga",
    "case-studies",
    "reference-architecture",
    "getting-started",
  ];
  assert.deepEqual(
    await evaluate(
      '[...document.querySelectorAll(".chapter-nav a")].map(link => link.hash.slice(1))',
    ),
    chapters,
  );
  for (const id of chapters) {
    await click(`.chapter-nav a[href="#${id}"]`);
    await until(
      () =>
        evaluate(
          `document.querySelector(".chapter-nav [aria-current]")?.hash === "#${id}"`,
        ),
      `active chapter ${id}`,
    );
  }

  await evaluate(`Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: {writeText: async text => { window.copiedCommand = text; }},
  })`);
  for (const id of [
    "databases",
    "query",
    "mrva",
    "sarif",
    "sqlite",
    "duckdb",
    "install-host",
    "install-command",
    "install-first-run",
  ]) {
    await openDoorway(id);
    assert.ok(
      await evaluate(
        'document.querySelector("#doorway").contains(document.activeElement)',
      ),
      `Focus outside ${id} dialog`,
    );
    await key("Tab", "Tab", 9);
    assert.ok(
      await evaluate(
        'document.querySelector("#doorway").contains(document.activeElement)',
      ),
      "Tab escaped the modal",
    );
    const labels = await evaluate(
      '[...document.querySelectorAll("#doorway [data-copy]")].map(button => button.getAttribute("aria-label"))',
    );
    for (const label of labels) {
      await copyCommand(label);
      assert.ok(
        await evaluate(
          'document.querySelector("#doorway-feedback").textContent.startsWith("Copied")',
        ),
        "Copy feedback must be available inside the modal",
      );
    }
    await key("Escape", "Escape", 27);
    assert.equal(
      await evaluate('document.querySelector("#doorway").open'),
      false,
    );
    assert.ok(
      await evaluate(
        `document.activeElement === document.querySelector('[data-doorway][href="#${id}"]')`,
      ),
      `Focus did not return to ${id}`,
    );
  }

  await openDoorway("query");
  await click('#doorway a[href="#inputs"]');
  assert.ok(
    await evaluate(
      'document.querySelector("#inputs").open && !document.querySelector("#doorway").open && location.hash === "#inputs"',
    ),
    "Doorway links must reveal the matching milestone",
  );
  await copyCommand("Copy step 08 command");
  await evaluate(`navigator.clipboard.writeText = async () => {
    throw new Error("Clipboard denied for this check");
  }`);
  await click('[data-copy][aria-label="Copy step 09 command"]');
  await until(
    () =>
      evaluate(
        'document.querySelector("#copy-feedback").textContent.includes("Clipboard unavailable")',
      ),
    "explicit clipboard failure",
  );
  assert.equal(
    await evaluate("getSelection().toString()"),
    commands["Copy step 09 command"],
  );

  await openDoorway("install-command");
  await click(
    '#doorway [data-copy][aria-label="Copy CGA dispatcher installation commands"]',
  );
  await until(
    () =>
      evaluate(
        'document.querySelector("#doorway-feedback").textContent.includes("Clipboard unavailable")',
      ),
    "clipboard failure inside the modal",
  );
  assert.equal(
    await evaluate("getSelection().toString()"),
    commands["Copy CGA dispatcher installation commands"],
  );
  await key("Escape", "Escape", 27);

  await openDoorway("duckdb");
  await click("#close-doorway");
  assert.equal(
    await evaluate('document.querySelector("#doorway").open'),
    false,
  );
  await openDoorway("sqlite");
  await clickPoint(5, 5);
  assert.equal(
    await evaluate('document.querySelector("#doorway").open'),
    false,
  );

  await navigate(`${legacyURL}#results`, `${overviewURL}#results`);
  assert.ok(await evaluate('document.querySelector("#results").open'));
  await navigate(legacyURL, `${overviewURL}#reference-architecture`);
  for (const entry of entryURLs) {
    await navigate(entry, overviewURL);
    await navigate(
      `${entry}?from=index#reference-architecture`,
      `${overviewURL}?from=index#reference-architecture`,
    );
  }
  await navigate(`${overviewURL}#results`);
  await evaluate('location.hash = "#inputs"');
  await until(
    () => evaluate('document.querySelector("#inputs").open'),
    "hash-change disclosure",
  );

  for (const width of [1440, 1024, 768, 640, 390]) {
    await viewport(width);
    assert.ok(
      await evaluate("document.documentElement.scrollWidth <= innerWidth"),
      `Document overflows at ${width}px`,
    );
  }
  assert.ok(
    await evaluate(`(() => {
    const map = document.querySelector(".map-viewport");
    return map.scrollWidth > map.clientWidth;
  })()`),
    "The narrow diagram must scroll within its own viewport",
  );
  for (const id of ["duckdb", "install-host"]) {
    await openDoorway(id);
    assert.ok(
      await evaluate(`(() => {
      const dialog = document.querySelector("#doorway");
      const box = dialog.getBoundingClientRect();
      return dialog.scrollWidth <= dialog.clientWidth &&
        box.left >= 0 && box.right <= innerWidth;
    })()`),
      `Narrow ${id} dialog overflows`,
    );
    await click("#close-doorway");
  }
  await send("Emulation.setEmulatedMedia", { media: "print" });
  assert.ok(
    await evaluate("document.documentElement.scrollWidth <= innerWidth"),
    "Print layout overflows",
  );

  await createPage(false);
  await navigate(overviewURL);
  for (const id of ["databases", "install-command"]) {
    await click(`[data-doorway][href="#${id}"]`);
    if (!(await evaluate(`document.querySelector("#${id}").open`))) {
      await click(`#${id} > summary`);
    }
    assert.ok(
      await evaluate(
        `document.querySelector("#${id} .doorway-content").checkVisibility()`,
      ),
      `No-JavaScript details unavailable: ${id}`,
    );
  }
  await navigate(legacyURL, `${overviewURL}#reference-architecture`);
  for (const entry of entryURLs) {
    await navigate(entry, overviewURL);
  }

  await createPage();
  for (const reference of [
    "../cga/README.html",
    "../cga/cgauv/README.html",
    "../cga/cgabench/README.html",
  ]) {
    await navigate(new URL(reference, overviewURL).href);
    assert.deepEqual(
      await evaluate(visualStyle),
      overviewStyle,
      `${reference} must match the overview's typography and background`,
    );
    assert.equal(
      await evaluate(
        '[...document.querySelectorAll("h1")].filter(heading => heading.checkVisibility()).length',
      ),
      1,
      `${reference} must display its title only once`,
    );
    assert.ok(
      await evaluate(`(() => {
        const backgrounds = [...document.querySelectorAll("pre")]
          .map(block => getComputedStyle(block).backgroundColor);
        return backgrounds.length > 0 && new Set(backgrounds).size === 1 &&
          backgrounds[0] !== getComputedStyle(document.documentElement).backgroundColor &&
          backgrounds[0] !== "rgba(0, 0, 0, 0)";
      })()`),
      `${reference} code blocks must use consistent, distinct panel backgrounds`,
    );
    for (const width of [1440, 1024, 900, 768, 390]) {
      await viewport(width);
      assert.ok(
        await evaluate("document.documentElement.scrollWidth <= innerWidth"),
        `${reference} overflows at ${width}px`,
      );
      assert.ok(
        await evaluate(`(() => {
          const toc = document.querySelector("#TOC");
          const heading = [...document.querySelectorAll("h1")]
            .find(element => element.checkVisibility());
          const contents = toc.getBoundingClientRect();
          const title = heading.getBoundingClientRect();
          return innerWidth > 900
            ? getComputedStyle(toc).position === "fixed" && contents.right <= title.left
            : getComputedStyle(toc).position === "static" && contents.bottom <= title.top;
        })()`),
        `${reference} contents must be beside the text on desktop and above it on narrow screens`,
      );
    }
    const section = await evaluate(`(() => {
      const heading = document.querySelector("body > h2");
      return [...document.querySelectorAll("#TOC a")]
        .find(link => decodeURIComponent(link.hash.slice(1)) === heading.id)
        .getAttribute("href");
    })()`);
    await click(`#TOC a[href=${JSON.stringify(section)}]`);
    await until(
      () => evaluate(`location.hash === ${JSON.stringify(section)}`),
      `${reference} section navigation`,
    );
    assert.ok(
      await evaluate(`(() => {
        const box = document.getElementById(decodeURIComponent(location.hash.slice(1)))
          .getBoundingClientRect();
        return box.top >= 0 && box.top < innerHeight;
      })()`),
      `${reference} section navigation must reveal its heading`,
    );
    await viewport(794, 1123);
    await send("Emulation.setEmulatedMedia", { media: "print" });
    assert.ok(
      await evaluate(`document.documentElement.scrollWidth <= innerWidth &&
        getComputedStyle(document.querySelector("#TOC")).position === "static" &&
        [...document.querySelectorAll("pre")].every(block => block.scrollWidth <= block.clientWidth)`),
      `${reference} print layout must not overflow or retain a fixed sidebar`,
    );
    await send("Emulation.setEmulatedMedia", { media: "" });
  }
  assert.deepEqual(exceptions, [], "Page JavaScript exceptions");
  assert.deepEqual(
    requests.filter((url) => /^(https?|wss?):/.test(url)),
    [],
    "The overview and reference pages must not contact external resources or services",
  );
  console.log(
    "Overview and reference browser checks passed: offline navigation, doorways, keyboard focus, exact copies, redirects, matching reference styles, narrow/print layout, and no-JavaScript fallback.",
  );
} finally {
  for (const targetId of targets) {
    await send("Target.closeTarget", { targetId }, null);
  }
  socket.close();
}
