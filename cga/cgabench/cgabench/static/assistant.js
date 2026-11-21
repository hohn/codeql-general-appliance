"use strict";
(() => {
  const element = (id) => document.getElementById(id);
  const view = element("collapse-assistant");
  if (new URLSearchParams(location.search).get("view") !== "assistant") {
    let popup;
    view.onclick = () => {
      element("assistant-error").textContent = "";
      if (!popup || popup.closed) {
        popup = window.open(
          "./?view=assistant", `cga-bench-assistant-${location.host.replaceAll(":", "-")}`,
          "popup,width=1000,height=700,resizable=yes,scrollbars=yes",
        );
      }
      if (!popup) {
        element("assistant-error").textContent =
          "Allow pop-ups for this Bench page, then choose View > Copilot assistant again.";
        return;
      }
      popup.focus();
    };
    return;
  }
  document.title = "Copilot assistant | CGA Bench";
  document.body.classList.add("assistant-window");
  view.hidden = true;
  element("assistant-status").textContent = "Connecting...";
  const panel = document.querySelector(".assistant-panel");
  panel.hidden = false;
  panel.append(
    element("assistant-error"),
    element("assistant-popup").content.cloneNode(true),
  );
  let descriptor, terminal, fit, observer, epoch = 0, changing = false;
  let input = Promise.resolve();

  async function action(operation, values = {}) {
    const response = await fetch("api/assistant", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CGA-Bench": "1" },
      body: JSON.stringify({ operation, ...values }),
    });
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || `HTTP ${response.status}`);
    return value;
  }
  function error(reason) {
    element("assistant-error").textContent = reason.message || String(reason);
  }
  function controls() {
    element("assistant-connect").disabled = changing;
    element("assistant-start").disabled = changing || Boolean(descriptor?.running);
    element("assistant-stop").disabled = changing || !descriptor?.running;
  }
  function status(value) {
    descriptor = value;
    element("assistant-status").textContent = value.error
      ? value.error
      : value.running
        ? "Running - initialization and permission prompts in terminal"
        : value.id
          ? `Assistant exited (${value.exit_code ?? "stopped"}). Start a new session to restart.`
          : "Not started.";
    controls();
  }
  function enqueue(operation, values) {
    const id = descriptor?.id, current = epoch;
    input = input.then(async () => {
      if (current === epoch && descriptor?.running) {
        await action(operation, { id, ...values });
      }
    }).catch(error);
  }
  function resize() {
    if (!terminal || !element("assistant-terminal").getClientRects().length) return;
    fit.fit();
    if (descriptor?.running) {
      enqueue("resize", { columns: terminal.cols, rows: terminal.rows });
    }
  }
  async function read(current, id) {
    let cursor = 0;
    try {
      while (current === epoch) {
        const output = await action("read", { id, cursor });
        if (current !== epoch) return;
        if (output.reset) terminal.writeln("\r\n[Older buffered output was discarded]\r\n");
        await new Promise((resolve) => terminal.write(
          Uint8Array.from(atob(output.data), (character) => character.charCodeAt(0)), resolve,
        ));
        cursor = output.cursor;
        if (output.error) throw new Error(output.error);
        if (!output.running && !output.more) {
          status({ ...descriptor, ...output });
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, output.more ? 0 : 100));
      }
    } catch (reason) {
      if (current === epoch) {
        error(reason);
        element("assistant-status").textContent = "Connection lost. Reconnect to the existing assistant.";
      }
    }
  }
  async function connect(operation = "open") {
    if (changing) return;
    changing = true;
    ++epoch;
    controls();
    element("assistant-error").textContent = "";
    try {
      const value = await action(operation);
      terminal.reset();
      status(value);
      if (value.id) {
        read(epoch, value.id);
        resize();
        terminal.focus();
      }
    } catch (reason) {
      error(reason);
      element("assistant-status").textContent = "Assistant unavailable. Reconnect or start to retry.";
    } finally {
      changing = false;
      controls();
    }
  }
  element("assistant-connect").onclick = () => connect();
  element("assistant-start").onclick = () => connect("start");
  element("assistant-stop").onclick = async () => {
    if (changing || !descriptor?.running || !confirm("Stop the shared Copilot assistant for all tabs?")) return;
    changing = true;
    controls();
    try {
      await input;
      status(await action("stop", { id: descriptor.id }));
    } catch (reason) {
      error(reason);
    } finally {
      changing = false;
      controls();
    }
  };
  window.addEventListener("pagehide", () => { ++epoch; observer?.disconnect(); });
  try {
    terminal = new Terminal({ cursorBlink: true, scrollback: 3000, cols: 100, rows: 24 });
    fit = new FitAddon.FitAddon();
    terminal.loadAddon(fit);
    terminal.open(element("assistant-terminal"));
    terminal.onData((data) => enqueue("write", { data }));
    observer = new ResizeObserver(resize);
    observer.observe(element("assistant-terminal"));
    connect();
  } catch (reason) {
    error(reason);
    element("assistant-status").textContent = "Terminal unavailable.";
  }
})();
