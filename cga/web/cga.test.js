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
    setAttribute() {},
    addEventListener(name, callback) {
      this.listeners[name] = callback;
    },
  };
}

async function checkOverview(mount) {
  const ports = {
    cgadl: 8602,
    cgaql: 8603,
    cgamr: 8604,
    cgamu: 8605,
    cgasi: 8606,
    cgaex: 8608,
  };
  const slots = [
    element("cga-header", "cgasv", "/header"),
    element("", "cgadl", "/overview"),
    element("", "cgaql", "/overview"),
    element("", "cgamr", "/overview"),
    element("", "cgamu", "/overview"),
    element("", "cgasi", "/overview"),
    element("", "cgaex", "/overview"),
  ];
  const detail = element("cga-detail");
  const which = element("cga-detail-which");
  const analysis = element("cga-flow-analysis");
  const reload = element("cga-reload");
  const byID = {
    "cga-detail": detail,
    "cga-detail-which": which,
    "cga-reload": reload,
    "cga-theme-toggle": element("cga-theme-toggle"),
  };
  const requests = [];
  const context = {
    window: { CGA_CONFIG: mount
      ? Object.fromEntries([...Object.keys(ports), "cgasv", "cgamx"].map(comp => [comp, `${mount}/${comp}`]))
      : {} },
    document: {
      documentElement: { dataset: {} },
      hidden: false,
      getElementById(id) {
        return byID[id];
      },
      querySelectorAll(selector) {
        return selector === ".cga-flow" ? [analysis] : slots;
      },
    },
    fetch: async (url) => {
      requests.push(url);
      return { ok: true, text: async () => `<p>${url}</p>` };
    },
  };
  vm.createContext(context);
  const source = fs.readFileSync(path.join(__dirname, "cga.js"), "utf8");
  vm.runInContext(source, context);

  // Select while the initial refresh is still in flight. The click must not
  // be swallowed by that refresh.
  await analysis.listeners.click({
    target: { closest: () => ({ dataset: { comp: "cgaex" } }) },
  });
  assert.equal(which.textContent, "cgaex");
  assert.equal(detail.dataset.comp, "cgaex");

  for (const [flow, selected] of [
    [analysis, "cgasi"],
    [analysis, "cgaex"],
  ]) {
    requests.length = 0;
    await flow.listeners.click({
      target: { closest: () => ({ dataset: { comp: selected } }) },
    });

    for (const [comp, port] of Object.entries(ports)) {
      assert.ok(
        requests.includes(`${mount ? `${mount}/${comp}` : `http://127.0.0.1:${port}`}/overview`),
        `${comp}/overview was not refreshed after selecting ${selected}`,
      );
    }
    assert.ok(requests.includes(`${mount ? `${mount}/${selected}` : `http://127.0.0.1:${ports[selected]}`}/detail`));
    assert.equal(which.textContent, selected);
    assert.equal(detail.dataset.comp, selected);
  }
}

for (const mount of [null, "/analysis", "/flow"]) {
  test(`clicking one overview refreshes all overviews and its detail (${mount || "direct"})`,
    () => checkOverview(mount));
}
