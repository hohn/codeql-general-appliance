import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import {mkdtemp, readFile, rm} from "node:fs/promises";
import {createServer} from "node:http";
import {tmpdir} from "node:os";
import {join} from "node:path";

const page = await readFile(process.argv[2], "utf8");
const profile = await mkdtemp(join(tmpdir(), "sysview-pause-"));
let mode = "delayed";
let requests = 0;
let release;
const small = {
  generated_at: "small", refresh_ms: 60000,
  jobs: [{user: "bob", session_id: "one", owner: "owner", repo: "repo", status: 2}],
  workers: [{worker_id: "worker-one", status: 0, hb_age_s: 15, jobs_completed: 1}],
  spawns: [], heartbeat_expiry_s: 10,
};
const large = JSON.stringify({
  ...small, generated_at: "large",
  jobs: Array.from({length: 12000}, (_, i) => ({
    ...small.jobs[0], session_id: `session-${Math.floor(i / 200)}`, repo: `repo-${i}`,
  })),
  padding: "x".repeat(37 * 1024 * 1024),
});
const instrumentation = `
var originalRenderSteps = renderSteps;
var renderedSnapshots = [];
var renderStepCount = 0;
renderSteps = function* (data) {
  for (var step of originalRenderSteps(data)) {
    renderStepCount++;
    yield step;
  }
  renderedSnapshots.push(data.generated_at);
};
`;
const server = createServer((request, response) => {
  if (request.url === "/sysview/data") {
    requests++;
    response.setHeader("Content-Type", "application/json");
    if (mode === "delayed") release = () => response.end(JSON.stringify(small));
    else if (mode === "error") {
      response.statusCode = 503;
      response.end("unavailable");
    } else response.end(mode === "large" ? large : JSON.stringify(small));
  } else {
    response.setHeader("Content-Type", "text/html");
    response.end(page.replace("var refreshMs = 500;", instrumentation + "\nvar refreshMs = 500;"));
  }
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const browser = spawn("chromium", [
  "--headless", "--disable-gpu", "--disable-background-networking", "--disable-sync",
  "--no-first-run", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank",
], {stdio: "ignore"});
let socket;
async function until(check, description) {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    const result = await check();
    if (result) return result;
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  throw new Error(`Timed out: ${description}`);
}
try {
  const active = await until(async () => {
    try { return await readFile(join(profile, "DevToolsActivePort"), "utf8"); }
    catch (error) { if (error.code !== "ENOENT") throw error; }
  }, "Chromium startup");
  const [port, endpoint] = active.trim().split("\n");
  socket = new WebSocket(`ws://127.0.0.1:${port}${endpoint}`);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, {once: true});
    socket.addEventListener("error", reject, {once: true});
  });
  let sequence = 0;
  const pending = new Map();
  const exceptions = [];
  socket.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    if (message.method === "Runtime.exceptionThrown") exceptions.push(message.params);
    if (!pending.has(message.id)) return;
    const [resolve, reject] = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) reject(new Error(JSON.stringify(message.error)));
    else resolve(message.result);
  });
  function send(method, params = {}, sessionId) {
    const id = ++sequence;
    return new Promise((resolve, reject) => {
      pending.set(id, [resolve, reject]);
      socket.send(JSON.stringify({id, method, params, sessionId}));
    });
  }
  const {targetId} = await send("Target.createTarget", {url: "about:blank"});
  const {sessionId} = await send("Target.attachToTarget", {targetId, flatten: true});
  await send("Runtime.enable", {}, sessionId);
  async function evaluate(expression) {
    const result = await send("Runtime.evaluate", {
      expression, returnByValue: true, awaitPromise: true,
    }, sessionId);
    assert.equal(result.exceptionDetails, undefined, JSON.stringify(result.exceptionDetails));
    return result.result.value;
  }
  async function clickPause() {
    const point = await evaluate(`(() => {
      var r = document.getElementById("pauseBtn").getBoundingClientRect();
      return {x: r.left + r.width / 2, y: r.top + r.height / 2};
    })()`);
    const started = Date.now();
    for (const type of ["mousePressed", "mouseReleased"]) {
      await send("Input.dispatchMouseEvent", {
        type, ...point, button: "left", clickCount: 1,
      }, sessionId);
    }
    return Date.now() - started;
  }
  await send("Page.navigate", {url: `http://127.0.0.1:${server.address().port}/sysview`}, sessionId);
  await until(() => release, "initial pending request");
  await clickPause();
  assert.equal(await evaluate('document.getElementById("pauseBtn").textContent'), "Resume");
  assert.equal(await evaluate("activeRefresh"), null);
  release();
  await new Promise(resolve => setTimeout(resolve, 100));
  assert.deepEqual(await evaluate("renderedSnapshots"), []);
  assert.equal(requests, 1);
  assert.match(await evaluate('document.getElementById("meta").textContent'), /paused/);

  mode = "large";
  await clickPause();
  await until(() => evaluate("renderStepCount > 14000 && !renderedSnapshots.length"), "large DOM render yielding");
  const elapsed = await clickPause();
  assert.ok(elapsed < 1000, `Pause took ${elapsed} ms during a 37 MB refresh`);
  assert.equal(await evaluate('document.getElementById("pauseBtn").textContent'), "Resume");
  const steps = await evaluate("renderStepCount");
  await new Promise(resolve => setTimeout(resolve, 100));
  assert.equal(await evaluate("renderStepCount"), steps);
  assert.deepEqual(await evaluate("renderedSnapshots"), []);
  assert.equal(requests, 2);

  mode = "small";
  await clickPause();
  await until(() => evaluate('renderedSnapshots.includes("small")'), "resume renders fresh snapshot");
  assert.equal(await evaluate('document.querySelectorAll(".job-repo").length'), 1);
  assert.equal(await evaluate('document.querySelectorAll("#workers .s-down").length'), 1);
  assert.equal(await evaluate('document.querySelectorAll(".paused-tag").length'), 0);
  const completedRequests = requests;
  await clickPause();
  await new Promise(resolve => setTimeout(resolve, 100));
  assert.equal(requests, completedRequests);

  mode = "large";
  await clickPause();
  await until(() => evaluate('renderedSnapshots.includes("large")'), "complete large snapshot");
  await clickPause();
  assert.equal(await evaluate('document.querySelectorAll(".job-repo").length'), 12000);
  assert.equal(await evaluate('document.querySelectorAll("table.jobs tbody tr").length'), 60);
  await evaluate(`document.querySelector('[data-key="user:bob"] > .box-title').click()`);
  assert.equal(await evaluate(`collapsed.has("user:bob")`), true);

  // Replay's synchronous entry point still renders the same shared structures.
  await evaluate(`render(${JSON.stringify({...small, generated_at: "replay"})})`);
  assert.match(await evaluate('document.getElementById("meta").textContent'), /replay/);
  assert.equal(await evaluate('document.querySelectorAll(".job-repo").length'), 1);
  assert.equal(await evaluate(`document.querySelector('[data-key="user:bob"]').classList.contains("collapsed")`), true);
  mode = "error";
  await clickPause();
  await until(() => evaluate('document.getElementById("meta").textContent.includes("HTTP 503")'), "visible fetch error");
  await clickPause();
  assert.deepEqual(exceptions, []);
  await send("Target.closeTarget", {targetId});
} finally {
  socket?.close();
  browser.kill();
  await new Promise(resolve => browser.once("exit", resolve));
  server.closeAllConnections();
  await new Promise(resolve => server.close(resolve));
  await rm(profile, {recursive: true, force: true});
}
