"use strict";

window.CGAHelpReferences = (() => {
  const model = JSON.parse(document.getElementById("help-data").textContent);
  const {elements, targets, generation} = model.references;
  const pageRoot = elements.find(entry => entry.kind === "help-pages").vid;
  const documentURL = location.href.split("#")[0];
  const context = {document: documentURL, frontier: generation};

  function pageRef(command, section) {
    const path = command.split(" ").slice(1);
    if (section) path.push("section", section.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""));
    return [pageRoot, ...path].join(",");
  }

  function mark(element, command, section) {
    const ref = pageRef(command, section);
    if (targets[ref]) element.dataset.helpRef = ref;
  }

  function markDocument(element, href) {
    const ref = model.references.documents[href];
    if (!ref) throw new Error(`Unregistered help document: ${href}`);
    element.dataset.helpRef = ref;
    element.dataset.helpDocumentRef = ref;
  }

  function markGroup(element, label) {
    const ref = model.references.groups[label];
    if (!ref) throw new Error(`Unregistered help group: ${label}`);
    element.dataset.helpRef = ref;
    element.dataset.helpGroupRef = ref;
  }

  function qualify(ref) {
    return "cga://help?" + new URLSearchParams({
      document: documentURL, ref, at: generation,
    });
  }

  function link(ref) {
    return documentURL + "#" + new URLSearchParams({vid: ref, at: generation});
  }

  function inspect(ref) {
    const target = targets[ref];
    if (!target) throw new Error(`Unknown help reference: ${ref}`);
    let command = target.command;
    if (ref === ":9g2") command = document.getElementById("top-title").textContent;
    if (ref === ":qlk") command = document.getElementById("bottom-title").textContent;
    const page = model.pages[command];
    const help = page ? {
      command: page.command,
      sections: target.section
        ? page.sections.filter(section => section.heading === target.section)
        : page.sections,
    } : null;
    const children = page ? page.children.map(child => child.id) : target.commands || [];
    const relations = children.filter(command => targets[pageRef(command)]).map(command => ({
      type: page ? "subcommand" : "command", reference: pageRef(command), label: command,
      link: link(pageRef(command)),
    }));
    if (target.section) relations.unshift({
      type: "page", reference: pageRef(command), label: command, link: link(pageRef(command)),
    });
    return {
      schema: "cga.help.inspection.v1", reference: ref,
      qualified_ref: qualify(ref), link: link(ref), generation,
      opened_at: new Date().toISOString(), target,
      properties: {
        document: documentURL, generated_at: model.generated_at,
        active_command: document.getElementById("top-title").textContent,
        active_subcommand: document.getElementById("bottom-title").textContent,
        search: document.getElementById("search-query").value,
        regex: document.getElementById("search-regex").checked,
      },
      help, relations,
    };
  }

  function openInspector({ref, color}) {
    const identity = new URL(ref);
    if (identity.protocol !== "cga:" || identity.hostname !== "help" ||
        identity.searchParams.get("document") !== documentURL) {
      throw new Error("The reference belongs to a different help document");
    }
    if (identity.searchParams.get("at") !== generation) {
      throw new Error("The requested help snapshot is not retained in this file");
    }
    const value = inspect(identity.searchParams.get("ref"));
    const popup = window.open("", "_blank", "popup,width=1000,height=850");
    if (!popup) return null;
    const doc = popup.document;
    doc.title = `${value.reference} - CGA help inspector`;
    doc.body.className = "cga-inspector";
    doc.documentElement.dataset.appearance = "grayscale";
    function element(tag, text, parent = doc.body) {
      const node = doc.createElement(tag);
      if (text !== undefined) node.textContent = text;
      parent.append(node);
      return node;
    }
    const style = element("style", document.getElementById("vid-style").textContent, doc.head);
    style.textContent += "\nbody.cga-inspector{height:auto;display:block;overflow:auto} textarea{box-sizing:border-box;width:100%;height:20rem;font:12px ui-monospace,monospace} #color-bar{background:var(--vid-color)}";
    doc.body.style.setProperty("--vid-color", `hsl(${color} 65% 78%)`);
    element("div").id = "color-bar";
    const header = element("header");
    element("h1", value.target.label, header);
    element("code", value.reference, header).id = "reference";
    element("p", "Offline pinned help snapshot. No service, terminal, or command is started.");
    element("p", value.qualified_ref).id = "qualified-reference";
    const actions = element("div");
    actions.className = "terminal-actions";
    const error = element("p");
    error.id = "error";
    error.setAttribute("role", "alert");
    const contextText = JSON.stringify(value, null, 2);
    const manual = element("textarea", undefined, actions);
    manual.hidden = true;
    manual.readOnly = true;
    manual.setAttribute("aria-label", "Text selected for manual copying");
    for (const [label, text] of [["Copy context", contextText], ["Copy link", value.link]]) {
      const button = element("button", label, actions);
      button.type = "button";
      button.addEventListener("click", async () => {
        error.textContent = "";
        manual.hidden = true;
        try {
          if (!popup.navigator.clipboard?.writeText) throw new Error("clipboard access is unavailable");
          await popup.navigator.clipboard.writeText(text);
        } catch (reason) {
          manual.value = text;
          manual.hidden = false;
          manual.focus();
          manual.select();
          error.textContent = `Could not copy: ${reason.message}. Text selected for manual copying.`;
        }
      });
    }
    element("h2", "Properties");
    element("pre", JSON.stringify(value.properties, null, 2));
    if (value.help) {
      element("h2", value.help.command);
      for (const section of value.help.sections) {
        element("h3", section.heading);
        element("pre", section.text);
      }
    }
    element("h2", "Related help");
    const relations = element("div");
    relations.id = "relations";
    for (const relation of value.relations) {
      const anchor = element("a", `${relation.type}: ${relation.reference} ${relation.label}`, relations);
      anchor.href = relation.link;
      anchor.target = "_blank";
      anchor.rel = "noopener";
    }
    element("h2", "Context for humans and LLMs");
    const contextField = element("textarea");
    contextField.id = "context";
    contextField.readOnly = true;
    contextField.setAttribute("aria-label", "Pinned help context JSON");
    contextField.value = contextText;
    return popup;
  }

  window.CGAVIDConfig = {
    registry: {elements, context},
    qualify,
    reference: (entry, element) => element.dataset.helpRef || entry.vid,
    openInspector,
  };

  function navigate(showPage) {
    function reveal() {
      const parameters = new URLSearchParams(location.hash.slice(1));
      const ref = parameters.get("vid");
      if (!ref) return;
      const target = targets[ref];
      const at = parameters.get("at");
      if (!target || (at && at !== generation)) {
        document.getElementById("status").textContent = !target
          ? `Unknown help reference: ${ref}` : "The requested help snapshot is not retained in this file";
        return;
      }
      if (target.command) showPage(target.command);
      requestAnimationFrame(() => {
        const badge = [...document.querySelectorAll(".cga-vid")].find(node => node.dataset.vid === ref);
        if (!badge) return;
        for (let parent = badge.parentElement; parent; parent = parent.parentElement) {
          if (parent.matches("details")) parent.open = true;
        }
        badge.scrollIntoView({block: "nearest"});
        badge.focus({preventScroll: true});
      });
    }
    window.CGAVIDConfig.ready = reveal;
    window.addEventListener("hashchange", reveal);
  }
  return {mark, markDocument, markGroup, navigate};
})();
