const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const script = fs
  .readFileSync(path.join(__dirname, "../cgauv/static/cgauv.js"), "utf8")
  .split("function el(")[0];

test("summary collapse and expansion synchronize visibility and accessible labels", () => {
  const body = { hidden: false };
  const attributes = {};
  let click;
  const control = {
    addEventListener: (name, listener) => {
      assert.equal(name, "click");
      click = listener;
    },
    setAttribute: (name, value) => (attributes[name] = value),
  };
  const document = {
    getElementById: (id) => {
      assert.ok(["collapse-system", "system-body"].includes(id));
      return id === "collapse-system" ? control : body;
    },
  };
  vm.runInNewContext(`${script}\ninitializeSystemSummary();`, { document });
  assert.equal(body.hidden, false);
  for (const hidden of [true, false, true]) {
    click();
    assert.equal(body.hidden, hidden);
    assert.equal(control.textContent, hidden ? "\u25b8" : "\u25be");
    assert.equal(attributes["aria-expanded"], String(!hidden));
    const label = `${hidden ? "expand" : "collapse"} MRVA system summary`;
    assert.equal(attributes["aria-label"], label);
    assert.equal(control.title, label);
  }
});
