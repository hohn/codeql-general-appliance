"use strict";
(async () => {
  const $ = (id) => document.getElementById(id);
  const query = new URLSearchParams(location.search);
  const hue = Number(query.get("color") || "166");
  const grayscale = query.get("appearance") === "grayscale";
  if (grayscale) document.documentElement.dataset.appearance = "grayscale";
  document.documentElement.style.setProperty(
    "--vid-color", grayscale ? "#d5d5d5" : `hsl(${Number.isFinite(hue) ? hue % 360 : 166} 65% 78%)`);
  let descriptor, terminal, fit, observer, stopped = false, input = Promise.resolve();
  function error(value) { $("error").textContent = value.message || String(value); }
  async function action(operation, values = {}) {
    const response = await fetch("api/vid/terminal", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CGA-VID": "1" },
      body: JSON.stringify({ operation, id: descriptor?.id, ...values }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    return result;
  }
  function enqueue(operation, values = {}) {
    input = input.then(() => { if (!stopped) return action(operation, values); }).catch(error);
  }
  function close() {
    const wasStopped = stopped;
    stopped = true;
    observer?.disconnect();
    if (!descriptor || wasStopped) return;
    fetch("api/vid/terminal", {
      method: "POST", keepalive: true,
      headers: { "Content-Type": "application/json", "X-CGA-VID": "1" },
      body: JSON.stringify({ operation: "stop", id: descriptor.id }),
    }).catch(error);
  }
  window.addEventListener("pagehide", close);
  try {
    const response = await fetch(`api/vid?${new URLSearchParams({ ref: query.get("ref") || "" })}`);
    const value = await response.json();
    if (!response.ok) throw new Error(value.error);
    $("reference").textContent = `${value.ref} - ${value.label}`;
    $("qualified-reference").textContent = value.pinned_ref;
    document.title = value.ref + " | CGA inspector";
    $("context").textContent = `Workflow: ${value.context.workflow}; chain: ${
      value.context.chain || "(none)"}; experiment: ${
      value.context.experiment || "(none)"}; fact frontier: ${value.context.frontier || "(empty)"}`;
    $("properties").textContent = JSON.stringify(value.properties, null, 2);
    $("facts").textContent = JSON.stringify(value.facts, null, 2);
    $("copy").onclick = async () => {
      try { await navigator.clipboard.writeText(value.pinned_ref); }
      catch (reason) { error(reason); }
    };
    for (const relation of value.relations) {
      const link = document.createElement("a");
      const parameters = new URLSearchParams({ ref: relation.qualified_ref, color: String(hue) });
      if (grayscale) parameters.set("appearance", "grayscale");
      link.href = "vid?" + parameters;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = `${relation.relation}: ${relation.ref}`;
      $("relations").append(link);
    }
    terminal = new Terminal({ cursorBlink: true, convertEol: false, scrollback: 3000 });
    fit = new FitAddon.FitAddon();
    terminal.loadAddon(fit);
    terminal.open($("terminal"));
    fit.fit();
    descriptor = await action("open", {
      ref: value.pinned_ref, columns: terminal.cols, rows: terminal.rows,
    });
    if (stopped) { stopped = false; close(); return; }
    $("terminal-status").textContent = "Separate shell; closes with this window.";
    $("insert").disabled = false;
    $("stop").disabled = false;
    terminal.onData((data) => { enqueue("write", { data }); });
    $("insert").onclick = () => { enqueue("insert"); terminal.focus(); };
    $("stop").onclick = async () => {
      try {
        await action("stop"); stopped = true; observer.disconnect();
        $("terminal-status").textContent = "Terminal stopped.";
        $("insert").disabled = true; $("stop").disabled = true;
      } catch (reason) { error(reason); }
    };
    observer = new ResizeObserver(() => {
      fit.fit();
      if (!stopped) action("resize", { columns: terminal.cols, rows: terminal.rows }).catch(error);
    });
    observer.observe($("terminal"));
    let cursor = 0;
    while (!stopped) {
      const output = await action("read", { cursor });
      if (stopped) break;
      if (output.reset) terminal.writeln("\r\n[Older buffered output was discarded]\r\n");
      terminal.write(Uint8Array.from(atob(output.data), (character) => character.charCodeAt(0)));
      cursor = output.cursor;
      if (output.error) throw new Error(output.error);
      if (!output.running && !output.more) {
        $("terminal-status").textContent = `Shell exited (${output.exit_code}).`;
        $("insert").disabled = true;
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, output.more ? 0 : 100));
    }
  } catch (reason) {
    error(reason); close();
    $("terminal-status").textContent = "Terminal unavailable.";
  }
})();
