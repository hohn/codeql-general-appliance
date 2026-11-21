"use strict";
window.CGAVID = (() => {
  const options = window.CGAVIDConfig || {};
  let context, registry, scheduled = false, watcher;
  const attached = new WeakMap(), popups = new Map();
  function full(ref, value = context) {
    if (!value) throw new Error("CGA reference context is not loaded");
    if (options.qualify) return options.qualify(ref, value);
    return "cga://vid?" + new URLSearchParams({
      workflow: value.workflow, chain: value.chain, experiment: value.experiment,
      ref, at: value.frontier,
    });
  }
  function color(ref) {
    let hash = 0;
    for (const character of ref) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
    return hash % 360;
  }
  function place(element, badge) {
    let label = element;
    if (element.matches(".disclosure-button")) {
      const heading = element.nextElementSibling;
      if (heading?.matches("h1, h2, h3, span")) label = heading;
    } else if (element.matches("form")) {
      label = element.querySelector('button:not([type]), button[type="submit"]') || element;
    } else if (element.matches("label")) {
      const text = [...element.childNodes].find(
        (node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim());
      label = element.querySelector(":scope > .cga-vid-label");
      if (!label && text) {
        label = document.createElement("span");
        label.className = "cga-vid-label";
        text.replaceWith(label);
        label.append(text);
      }
      label ||= element;
    } else if (!element.matches("button, a, input, select, [role=button]")) {
      label = element.querySelector(":scope > h2, :scope > h3, :scope > span") || element;
    }
    if (label.matches("button, a, input, select, [role=button]")) {
      let pair = label.parentElement;
      if (!pair.classList.contains("cga-vid-control")) {
        pair = document.createElement("span");
        pair.className = "cga-vid-control";
        label.before(pair);
        pair.append(label);
      }
      pair.append(badge);
      pair.hidden = label.hidden;
    } else {
      label.append(badge);
    }
  }
  function attach(element, ref, value = context) {
    if (!element || !value || !ref) return;
    if (element.getAttribute("role") === "separator") return;
    const previous = attached.get(element);
    const key = full(ref, value);
    if (previous?.key === key && previous.badge.isConnected) {
      if (previous.badge.hidden !== element.hidden) previous.badge.hidden = element.hidden;
      const pair = element.parentElement;
      if (pair?.classList.contains("cga-vid-control") && pair.hidden !== element.hidden) {
        pair.hidden = element.hidden;
      }
      return;
    }
    const identity = new URL(key);
    identity.searchParams.delete("at");
    const visualKey = identity.href;
    previous?.badge.remove();
    previous?.errors.forEach((error) => error.remove());
    const badge = document.createElement("button");
    badge.className = "cga-vid";
    badge.type = "button";
    const symbol = document.createElement("span");
    symbol.className = "cga-vid-symbol";
    symbol.setAttribute("aria-hidden", "true");
    badge.append(symbol);
    badge.dataset.vid = ref;
    badge.dataset.vidIdentity = visualKey;
    badge.hidden = element.hidden;
    badge.title = `Click to copy ${ref}; double-click to copy and open its pinned CGA inspector`;
    badge.setAttribute("aria-label", `Copy ${ref}; double-click to inspect CGA element`);
    const hue = color(visualKey);
    badge.style.setProperty("--vid-color", `hsl(${hue} 65% 78%)`);
    if (popups.has(visualKey)) badge.classList.add("cga-vid-active");
    const errors = [];
    function report(message) {
      if (errors.length) {
        errors[0].textContent += "\n" + message;
        return;
      }
      const error = document.createElement("span");
      error.className = "cga-vid-error";
      error.setAttribute("role", "alert");
      error.textContent = message;
      badge.after(error);
      errors.push(error);
    }
    async function copy() {
      try {
        if (!navigator.clipboard?.writeText) throw new Error("clipboard access is unavailable");
        await navigator.clipboard.writeText(ref);
      } catch (reason) {
        report(`Could not copy ${ref}: ${reason.message}`);
      }
    }
    badge.addEventListener("keydown", (event) => event.stopPropagation());
    badge.addEventListener("keyup", (event) => event.stopPropagation());
    function copyReference(event) {
      event.preventDefault(); event.stopPropagation();
      errors.splice(0).forEach((error) => error.remove());
      copy();
    }
    badge.onclick = copyReference;
    badge.ondblclick = (event) => {
      copyReference(event);
      const parameters = new URLSearchParams({ ref: key, color: String(hue) });
      if (document.body.dataset.presentation === "apple") parameters.set("appearance", "grayscale");
      let popup;
      try {
        popup = options.openInspector
          ? options.openInspector({ref: key, shortRef: ref, color: hue})
          : window.open("vid?" + parameters, "_blank", "popup,width=1000,height=850");
      } catch (reason) {
        report(`Could not inspect ${ref}: ${reason.message}`);
        return;
      }
      if (!popup) {
        report("Allow pop-ups to open the CGA inspector.");
        return;
      }
      if (!popups.has(visualKey)) popups.set(visualKey, new Set());
      popups.get(visualKey).add(popup);
      badge.classList.add("cga-vid-active");
      watcher ||= setInterval(() => {
        for (const [identity, windows] of popups) {
          for (const popup of windows) if (popup.closed) windows.delete(popup);
          if (!windows.size) popups.delete(identity);
        }
        document.querySelectorAll(".cga-vid-active").forEach((badge) => {
          badge.classList.toggle("cga-vid-active", popups.has(badge.dataset.vidIdentity));
        });
        if (!popups.size) { clearInterval(watcher); watcher = undefined; }
      }, 500);
    };
    place(element, badge);
    attached.set(element, { badge, key, errors });
  }
  function refresh() {
    scheduled = false;
    if (!registry || !context) return;
    const surface = document.body.dataset.vidSurface;
    for (const entry of registry.elements) {
      const selector = entry.selectors[surface];
      if (selector) document.querySelectorAll(selector).forEach((element) => {
        const path = element.dataset.session ? [element.dataset.session] : [];
        if (path.length && element.dataset.stage) path.push(element.dataset.stage);
        attach(element, options.reference
          ? options.reference(entry, element)
          : [entry.vid, ...path].join(","));
      });
    }
  }
  function schedule() {
    if (scheduled) return;
    scheduled = true;
    queueMicrotask(refresh);
  }
  async function initialize() {
    try {
      if (options.registry) {
        registry = options.registry;
      } else {
        const response = await fetch("api/vid/registry");
        registry = await response.json();
        if (!response.ok) throw new Error(registry.error || "VID registry unavailable");
      }
      context = context || registry.context;
      new MutationObserver(schedule).observe(document.body, {
        childList: true, subtree: true, attributes: true, attributeFilter: ["hidden"],
      });
      refresh();
      options.ready?.();
    } catch (reason) {
      const error = document.createElement("p");
      error.className = "cga-vid-error";
      error.setAttribute("role", "alert");
      error.textContent = `CGA references unavailable: ${reason.message}`;
      document.body.prepend(error);
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize);
  else initialize();
  return { attach, full, color, setContext(value) { context = value; schedule(); } };
})();
