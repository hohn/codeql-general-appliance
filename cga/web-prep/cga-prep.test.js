"use strict";

const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");

function element(id = "", comp = "", route = "") {
  return {
    id,
    dataset: { comp, route },
    innerHTML: "",
    textContent: "",
    listeners: {},
    addEventListener(name, callback) {
      this.listeners[name] = callback;
    },
  };
}

test("CGA preparation loads four preparation overviews and selected detail", async () => {
  const boxes = ["cgacv", "cgasp", "cgadb", "cgaqg"].map((name) =>
    element("", name, "/overview"),
  );
  const flow = element("cga-flow-preparation");
  const detail = element("cga-detail");
  const which = element("cga-detail-which");
  const reload = element("cga-reload");
  const byID = {
    "cga-flow-preparation": flow,
    "cga-detail": detail,
    "cga-detail-which": which,
    "cga-reload": reload,
  };
  const requests = [];
  const context = {
    window: { CGA_PREP_CONFIG: {} },
    document: {
      getElementById(id) {
        return byID[id];
      },
      querySelectorAll(selector) {
        return selector === ".cga-box[data-comp]" ? boxes : [];
      },
    },
    fetch: async (url) => {
      requests.push(url);
      return { ok: true, text: async () => `<p>${url}</p>` };
    },
  };

  vm.createContext(context);
  vm.runInContext(
    fs.readFileSync(path.join(__dirname, "cga-prep.js"), "utf8"),
    context,
  );
  await flow.listeners.click({
    target: { closest: () => ({ dataset: { comp: "cgadb" } }) },
  });

  for (const [component, port] of Object.entries({
    cgacv: 8501,
    cgasp: 8502,
    cgadb: 8503,
    cgaqg: 8504,
  })) {
    assert.ok(requests.includes(`http://127.0.0.1:${port}/overview`));
  }
  assert.ok(requests.includes("http://127.0.0.1:8503/detail"));
  assert.equal(which.textContent, "cgadb");
  assert.equal(detail.dataset.comp, "cgadb");
});
