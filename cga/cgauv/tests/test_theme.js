const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const script = fs
  .readFileSync(path.join(__dirname, "../cgauv/static/cgauv.js"), "utf8")
  .split("function el(")[0];

function initialize(stored, storageDisabled = false) {
  const listeners = {};
  const select = {
    value: "",
    addEventListener: (name, listener) => (listeners[name] = listener),
  };
  const document = {
    documentElement: { dataset: {} },
    getElementById: (id) => {
      assert.equal(id, "theme-select");
      return select;
    },
  };
  const storage = new Map([["cga.theme", stored]]);
  const localStorage = {
    getItem: (key) => {
      if (storageDisabled) throw new Error("storage disabled");
      return storage.get(key);
    },
    setItem: (key, value) => {
      if (storageDisabled) throw new Error("storage disabled");
      storage.set(key, value);
    },
  };
  vm.runInNewContext(`${script}\ninitializeTheme();`, { document, localStorage });
  return { document, select, listeners, storage };
}

test("restores all four themes and synchronizes the dropdown", () => {
  for (const theme of ["dark", "light", "font-on-white", "minimalist-bw"]) {
    const { document, select } = initialize(theme);
    assert.equal(document.documentElement.dataset.theme, theme);
    assert.equal(select.value, theme);
  }
});

test("dropdown changes apply and persist each theme", () => {
  const { document, select, listeners, storage } = initialize("dark");
  for (const theme of ["font-on-white", "minimalist-bw", "light", "dark"]) {
    listeners.change({ target: { value: theme } });
    assert.equal(document.documentElement.dataset.theme, theme);
    assert.equal(select.value, theme);
    assert.equal(storage.get("cga.theme"), theme);
    assert.equal(initialize(storage.get("cga.theme")).select.value, theme);
  }
});

test("missing or unknown preferences default to dark", () => {
  for (const stored of [undefined, "", "unknown"]) {
    assert.equal(initialize(stored).select.value, "dark");
  }
});

test("theme selection still works when browser storage is disabled", () => {
  const { document, select, listeners } = initialize("light", true);
  assert.equal(select.value, "dark");
  listeners.change({ target: { value: "font-on-white" } });
  assert.equal(document.documentElement.dataset.theme, "font-on-white");
  assert.equal(select.value, "font-on-white");
  listeners.change({ target: { value: "minimalist-bw" } });
  assert.equal(document.documentElement.dataset.theme, "minimalist-bw");
  assert.equal(select.value, "minimalist-bw");
});
