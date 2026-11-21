"use strict";

(() => {
  const model = JSON.parse(document.getElementById("help-data").textContent);
  const tree = document.getElementById("command-tree");
  const taskTree = document.getElementById("task-tree");
  const searchQuery = document.getElementById("search-query");
  const searchRegex = document.getElementById("search-regex");
  const searchStatus = document.getElementById("search-status");
  const topHelp = document.getElementById("top-help");
  const bottomHelp = document.getElementById("bottom-help");
  const topTitle = document.getElementById("top-title");
  const bottomTitle = document.getElementById("bottom-title");
  const status = document.getElementById("status");
  const panes = document.getElementById("right-panes");
  const divider = document.getElementById("pane-divider");
  let split = 0.6;
  let searchPattern = null;
  const matchingPages = new Set();

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function subcommandLink(child) {
    const link = element("a", child.match, "command-link");
    link.href = `#${encodeURIComponent(child.id)}`;
    link.title = `${child.command}\n${child.summary}`;
    link.dataset.command = child.id;
    window.CGAHelpReferences.mark(link, child.id);
    link.classList.toggle("search-match", matchingPages.has(child.id));
    link.addEventListener("click", event => {
      event.preventDefault();
      showBottom(child.id);
    });
    return link;
  }

  function helpSection(heading, command) {
    const section = element("section", undefined, "help-section");
    const title = element("h3", heading);
    window.CGAHelpReferences.mark(title, command, heading);
    section.append(title);
    return section;
  }

  function highlightMatches(container) {
    if (!searchPattern) return;
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const fragment = document.createDocumentFragment();
      let end = 0;
      for (const match of node.textContent.matchAll(new RegExp(searchPattern, "gim"))) {
        if (!match[0].length) continue;
        fragment.append(document.createTextNode(node.textContent.slice(end, match.index)));
        fragment.append(element("mark", match[0]));
        end = match.index + match[0].length;
      }
      if (end) {
        fragment.append(document.createTextNode(node.textContent.slice(end)));
        node.replaceWith(fragment);
      }
    }
  }

  function renderHelp(container, page, interactive) {
    container.replaceChildren();
    const linked = new Set();
    for (const content of page.sections) {
      const section = helpSection(content.heading, page.command);
      const pre = element("pre");
      const commandListing = ["Commands", "Positional Arguments"].includes(content.heading);
      const lines = content.text.split("\n");
      for (let index = 0; index < lines.length; index += 1) {
        const line = lines[index];
        const trimmed = line.trimStart();
        const child = interactive && commandListing && page.children.find(candidate => {
          if (!trimmed.startsWith(candidate.match)) return false;
          const next = trimmed[candidate.match.length];
          return next === undefined || /\s|\(/.test(next);
        });
        if (child) {
          const indent = line.slice(0, line.length - trimmed.length);
          pre.append(document.createTextNode(indent), subcommandLink(child));
          pre.append(document.createTextNode(trimmed.slice(child.match.length)));
          linked.add(child.id);
        } else {
          pre.append(document.createTextNode(line));
        }
        if (index < lines.length - 1) pre.append(document.createTextNode("\n"));
      }
      section.append(pre);
      container.append(section);
    }

    if (interactive) {
      const missing = page.children.filter(child => !linked.has(child.id));
      if (missing.length) {
        const section = helpSection("Subcommands", page.command);
        const list = element("ul", undefined, "fallback-links");
        for (const child of missing) {
          const item = element("li");
          item.append(subcommandLink(child), document.createTextNode(` - ${child.summary}`));
          list.append(item);
        }
        section.append(list);
        container.append(section);
      }
    } else if (page.children.length) {
      const section = helpSection("Continue in the shell", page.command);
      section.append(element("p", "Deeper help stays in the shell. These commands are never executed here."));
      for (const child of page.children) {
        const row = element("div", undefined, "shell-command");
        const input = element("input");
        input.type = "text";
        input.readOnly = true;
        input.value = child.command;
        input.setAttribute("aria-label", `Shell help for ${child.id}`);
        input.addEventListener("focus", () => input.select());
        const copy = element("button", "Copy");
        copy.type = "button";
        copy.setAttribute("aria-label", `Copy ${child.command}`);
        copy.addEventListener("click", async () => {
          status.textContent = "";
          if (!navigator.clipboard) {
            input.focus();
            input.select();
            status.textContent = "Clipboard unavailable; command selected for manual copying.";
            return;
          }
          try {
            await navigator.clipboard.writeText(child.command);
            status.textContent = `Copied: ${child.command}`;
          } catch (error) {
            input.focus();
            input.select();
            status.textContent = `Clipboard error: ${error.message}. Command selected for manual copying.`;
          }
        });
        row.append(input, copy);
        section.append(row);
      }
      container.append(section);
    }
    highlightMatches(container);
    container.scrollTop = 0;
    container.querySelector("mark")?.scrollIntoView({block: "nearest"});
  }

  function showBottom(id) {
    const page = model.pages[id];
    if (!page) {
      status.textContent = `Help page unavailable: ${id}`;
      return;
    }
    status.textContent = "";
    bottomTitle.textContent = page.command;
    renderHelp(bottomHelp, page, false);
    bottomTitle.focus({preventScroll: true});
  }

  function showTop(id) {
    const page = model.pages[id];
    status.textContent = "";
    topTitle.textContent = page.command;
    document.getElementById("selected-command").textContent = page.command;
    renderHelp(topHelp, page, true);
    bottomTitle.textContent = "No subcommand selected";
    bottomHelp.replaceChildren(element("p",
      "Click a subcommand in the command help above to inspect it here.", "placeholder"));
    bottomHelp.scrollTop = 0;
    for (const button of document.querySelectorAll(".outline .tree-item")) {
      if (button.dataset.command === id) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    }
  }

  function commandButton(command, tag = "button") {
    const button = element(tag, command.label, "tree-item");
    if (tag === "button") button.type = "button";
    button.dataset.command = command.id;
    window.CGAHelpReferences.mark(button, command.id);
    button.title = `${command.label}\n${command.id}\nNames: ${command.match}\n${command.summary}`;
    button.addEventListener("click", () => showTop(command.id));
    return button;
  }

  for (const [id, links] of [
    ["start-tree", model.start_here], ["llm-start-tree", model.llm_start_here],
    ["document-tree", model.tutorial_documents],
    ["system-tests-tree", model.system_tests],
  ]) {
    for (const entry of links) {
      const item = element("li");
      if (entry.href) {
        const link = element("a", entry.label, "tree-item");
        link.href = entry.href;
        link.title = `${entry.label}\n${entry.summary}`;
        link.target = "_blank";
        link.rel = "noopener";
        window.CGAHelpReferences.markDocument(link, entry.href);
        item.append(link);
      } else {
        item.append(commandButton(entry));
      }
      document.getElementById(id).append(item);
    }
  }

  const rootItem = element("li");
  const indexOutline = element("details");
  indexOutline.open = true;
  const children = element("ul");
  for (const [index, command] of model.tree.entries()) {
    const button = commandButton(command, index === 0 ? "summary" : "button");
    if (index === 0) {
      button.classList.add("index-summary");
      indexOutline.append(button);
    }
    else {
      const item = element("li");
      item.append(button);
      children.append(item);
    }
  }
  indexOutline.append(children);
  rootItem.append(indexOutline);
  tree.append(rootItem);
  for (const group of model.task_groups) {
    const item = element("li");
    const details = element("details", undefined, "task-group");
    details.open = true;
    const heading = element("summary", group.label);
    window.CGAHelpReferences.markGroup(heading, group.label);
    details.append(heading);
    const commands = element("ul");
    for (const command of group.commands) {
      const child = element("li");
      child.append(commandButton(command));
      commands.append(child);
    }
    details.append(commands);
    item.append(details);
    taskTree.append(item);
  }

  const searchable = Object.values(model.pages).map(page => ({
    page,
    text: [page.command, ...page.sections.map(section =>
      `${section.heading}:\n${section.text}`)].join("\n"),
  }));

  function searchHelp() {
    searchPattern = null;
    matchingPages.clear();
    searchStatus.hidden = !searchQuery.value;
    searchStatus.textContent = "";
    searchQuery.removeAttribute("aria-invalid");
    if (searchQuery.value) {
      try {
        searchPattern = new RegExp(searchRegex.checked ? searchQuery.value :
          searchQuery.value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "im");
      } catch (error) {
        searchStatus.textContent = `Invalid regular expression: ${error.message}`;
        searchQuery.setAttribute("aria-invalid", "true");
      }
    }
    if (searchPattern) {
      for (const {page, text} of searchable) {
        if (searchPattern.test(text)) matchingPages.add(page.command);
      }
      indexOutline.open = true;
    }
    let count = 0;
    for (const button of tree.querySelectorAll(".tree-item")) {
      const id = button.dataset.command;
      const matches = matchingPages.has(id) || (id !== "cga" &&
        model.pages[id].children.some(child => matchingPages.has(child.id)));
      button.classList.toggle("search-match", matches);
      if (matches) {
        count += 1;
        button.setAttribute("aria-description", "Search match in this command or its subcommand help");
      } else {
        button.removeAttribute("aria-description");
      }
    }
    if (searchPattern) {
      searchStatus.textContent = `${count} matching index ${count === 1 ? "entry" : "entries"}.`;
    }
    if (searchQuery.value) searchStatus.scrollIntoView({block: "start"});
    for (const container of [topHelp, bottomHelp]) {
      for (const mark of container.querySelectorAll("mark")) {
        mark.replaceWith(document.createTextNode(mark.textContent));
      }
      container.normalize();
      highlightMatches(container);
      for (const link of container.querySelectorAll(".command-link")) {
        link.classList.toggle("search-match", matchingPages.has(link.dataset.command));
      }
    }
  }

  document.getElementById("help-search").addEventListener("submit", event => {
    event.preventDefault();
    searchHelp();
  });
  document.getElementById("collapse-all").addEventListener("click", () => {
    for (const details of document.querySelectorAll(".outline details")) {
      details.open = false;
    }
  });
  document.getElementById("generated-at").textContent = `Generated ${model.generated_at}. Regenerate after CLI changes.`;

  function resizePanes(ratio) {
    const available = Math.max(0, panes.clientHeight - divider.offsetHeight);
    const minimum = Math.min(110, available / 3);
    const height = Math.max(minimum, Math.min(available - minimum, available * ratio));
    split = available > 0 ? height / available : 0.6;
    panes.style.gridTemplateRows = `${height}px ${divider.offsetHeight}px minmax(0, 1fr)`;
    const minPercent = available > 0 ? Math.round(minimum / available * 100) : 0;
    divider.setAttribute("aria-valuemin", String(minPercent));
    divider.setAttribute("aria-valuemax", String(100 - minPercent));
    divider.setAttribute("aria-valuenow", String(Math.round(split * 100)));
  }

  divider.addEventListener("pointerdown", event => {
    if (event.button !== 0) return;
    divider.setPointerCapture(event.pointerId);
    event.preventDefault();
  });
  divider.addEventListener("pointermove", event => {
    if (!divider.hasPointerCapture(event.pointerId)) return;
    const bounds = panes.getBoundingClientRect();
    resizePanes((event.clientY - bounds.top) / (bounds.height - divider.offsetHeight));
  });
  divider.addEventListener("pointerup", event => {
    if (divider.hasPointerCapture(event.pointerId)) divider.releasePointerCapture(event.pointerId);
  });
  divider.addEventListener("keydown", event => {
    if (!["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    if (event.key === "Home") resizePanes(0);
    else if (event.key === "End") resizePanes(1);
    else resizePanes(split + (event.key === "ArrowUp" ? -0.05 : 0.05));
  });
  window.addEventListener("resize", () => resizePanes(split));
  showTop(model.start_here.find((entry) => entry.id)?.id || "cga");
  window.CGAHelpReferences.navigate(showTop);
  resizePanes(split);
})();
