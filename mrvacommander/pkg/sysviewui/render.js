// Collapse state persists across refreshes, keyed by a stable per-box key.
var collapsed = new Set();
// Scroll offsets of session tables persist across refreshes with the same key.
var scrollState = new Map();
var HEARTBEAT_EXPIRY_S = 120;

function el(tag, cls, text) {
  var n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function box(levelClass, key, labelHtml) {
  var b = el("div", "box " + levelClass);
  b.dataset.key = key;
  if (collapsed.has(key)) b.classList.add("collapsed");
  var t = el("div", "box-title");
  var caret = el("span", "caret", "\u25be");
  var label = el("span", "box-label");
  label.innerHTML = labelHtml;
  var hint = el("span", "collapsed-hint", "(collapsed)");
  t.appendChild(caret);
  t.appendChild(label);
  t.appendChild(hint);
  t.addEventListener("click", function () {
    if (b.classList.toggle("collapsed")) collapsed.add(key);
    else collapsed.delete(key);
  });
  b.appendChild(t);
  return b;
}

function esc(s) {
  return String(s == null ? "" : s);
}

function serverCard(s, servedBy) {
  var role = s && s.role === "leader" ? "leader" : "backup";
  var online = !!(s && s.online);
  var placeholder = !!(s && s.placeholder);
  var card = el(
    "div",
    "server-card role-" +
      role +
      (online ? "" : " offline") +
      (placeholder ? " placeholder" : ""),
  );
  card.appendChild(el("span", "role-dot"));
  card.appendChild(el("span", "role-name", role));
  if (s && s.instance_id === servedBy) {
    card.appendChild(el("span", "endpoint-tag", "this endpoint"));
  }
  card.appendChild(
    el(
      "span",
      "server-id",
      s && s.instance_id ? s.instance_id : "(not registered)",
    ),
  );
  var health = placeholder
    ? "waiting"
    : online
      ? "online \u00b7 seen " + esc(s.hb_age_s) + "s ago"
      : "offline \u00b7 last seen " + esc(s.hb_age_s) + "s ago";
  card.appendChild(el("span", "server-health", health));
  return card;
}

function renderServers(servers, servedBy, legacyServer) {
  var host = document.getElementById("servers");
  if (!host) return;
  host.innerHTML = "";
  var rows = Array.isArray(servers) ? servers.slice() : [];
  // Old dumps had one endpoint-local server object. Keep them replayable.
  if (!rows.length && legacyServer) {
    rows.push({
      instance_id: legacyServer.instance_id,
      role: legacyServer.role,
      online: true,
      hb_age_s: 0,
    });
    if (!servedBy) servedBy = legacyServer.instance_id;
  }
  while (rows.length < 2) {
    var missingRole = rows.some(function (s) {
      return s.role === "leader";
    })
      ? "backup"
      : "leader";
    rows.push({ role: missingRole, online: false, placeholder: true });
  }
  rows.sort(function (a, b) {
    if (a.role !== b.role) return a.role === "leader" ? -1 : 1;
    return esc(a.instance_id).localeCompare(esc(b.instance_id));
  });
  rows.forEach(function (s) {
    host.appendChild(serverCard(s, servedBy));
  });
}

function* groupSteps(rows) {
  var users = new Map();
  for (var r of rows) {
    if (!users.has(r.user)) users.set(r.user, new Map());
    var sessions = users.get(r.user);
    if (!sessions.has(r.session_id)) sessions.set(r.session_id, []);
    sessions.get(r.session_id).push(r);
    yield;
  }
  return users;
}

function jobLabel(r) {
  return r.owner + "/" + r.repo;
}

function jobStatusName(s) {
  switch (s) {
    case 0:
      return "pending";
    case 1:
      return "in_progress";
    case 2:
      return "succeeded";
    case 3:
      return "failed";
    case 4:
      return "canceled";
    case 5:
      return "timed_out";
    case 6:
      return "queued";
    default:
      return "unknown";
  }
}

function statusIndicator(status) {
  var active = -1;
  var termCls = "p-ok";
  switch (status) {
    case 0:
      active = 0;
      break;
    case 6:
      active = 1;
      break;
    case 1:
      active = 2;
      break;
    case 2:
      active = 3;
      termCls = "p-ok";
      break;
    case 3:
    case 4:
    case 5:
      active = 3;
      termCls = "p-fail";
      break;
  }
  var fills = ["p-pending", "p-queued", "p-inprogress", termCls];
  var ind = el("div", "statind");
  for (var i = 0; i < 4; i++) {
    var sq = el("div", "statsq");
    if (i === active) {
      sq.classList.add("on");
      sq.classList.add(fills[i]);
    }
    ind.appendChild(sq);
  }
  ind.title = "status: " + jobStatusName(status);
  return ind;
}

function packLabel(jobs) {
  for (var i = 0; i < jobs.length; i++) {
    if (jobs[i] && jobs[i].pack_sha1) return "pack-" + jobs[i].pack_sha1;
  }
  return "pack-(unknown)";
}

function jobTitle(r) {
  return [
    "owner:     " + esc(r.owner),
    "repo:      " + esc(r.repo),
    "user:      " + esc(r.user),
    "session:   " + esc(r.session_id),
    "status:    " + esc(jobStatusName(r.status)),
    "started:   " + (r.started_at || "\u2014"),
    "completed: " + (r.completed_at || "\u2014"),
    "worker:    " + (r.worker_id || "\u2014"),
    "argo wf:   " + (r.argo_workflow_id || "\u2014"),
  ].join("\n");
}

function* sessionsTableSteps(sessions, scrollKey) {
  var vp = el("div", "jobs-table-viewport");
  vp.dataset.scrollkey = scrollKey;
  vp.addEventListener("scroll", function () {
    scrollState.set(scrollKey, { left: vp.scrollLeft, top: vp.scrollTop });
  });
  var table = el("table", "jobs");
  var maxJobs = 0;
  sessions.forEach(function (jobs) {
    if (jobs.length > maxJobs) maxJobs = jobs.length;
  });

  var thead = el("thead");
  var htr = el("tr");
  htr.appendChild(el("th", "col-repo", "session"));
  for (var i = 0; i < maxJobs; i++) {
    htr.appendChild(el("th", null, "job " + (i + 1)));
    yield;
  }
  thead.appendChild(htr);
  table.appendChild(thead);

  var tbody = el("tbody");
  for (var [sid, jobs] of sessions) {
    var tr = el("tr");
    var sc = el("td", "col-repo", String(sid));
    var pack = packLabel(jobs);
    sc.appendChild(el("span", "pack-id", pack));
    sc.title = "session " + sid + " (" + jobs.length + " jobs)\n" + pack;
    tr.appendChild(sc);
    for (var i = 0; i < maxJobs; i++) {
      var r = jobs[i];
      var td = el("td");
      if (r) {
        td.appendChild(el("div", "job-repo", jobLabel(r)));
        td.appendChild(statusIndicator(r.status));
        td.title = jobTitle(r);
      }
      tr.appendChild(td);
      yield;
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  vp.appendChild(table);
  return vp;
}

function* renderJobsSteps(rows) {
  var host = document.getElementById("jobs");
  if (!rows || !rows.length) {
    host.replaceChildren(el("div", "empty", "no jobs"));
    return;
  }
  var users = yield* groupSteps(rows);
  var usersBox = box(
    "level-users",
    "users",
    'users <span class="count">(' + users.size + ")</span>",
  );
  for (var [userName, sessions] of users) {
    var userJobs = 0;
    sessions.forEach(function (jobs) {
      userJobs += jobs.length;
    });
    var userBox = box(
      "level-user",
      "user:" + userName,
      '<span class="user-name">user: ' +
        esc(userName) +
        "</span> " +
        '<span class="count">(' +
        userJobs +
        " job" +
        (userJobs === 1 ? "" : "s") +
        ")</span>",
    );
    var sessionsBox = box(
      "level-sessions",
      "sessions:" + userName,
      'sessions <span class="count">(' + sessions.size + ")</span>",
    );
    sessionsBox.appendChild(yield* sessionsTableSteps(sessions, "sessions:" + userName));
    userBox.appendChild(sessionsBox);
    usersBox.appendChild(userBox);
    yield;
  }
  usersBox.querySelectorAll(".box").forEach(function (b) {
    b.classList.toggle("collapsed", collapsed.has(b.dataset.key));
  });
  usersBox.classList.toggle("collapsed", collapsed.has(usersBox.dataset.key));
  host.replaceChildren(usersBox);
  host.querySelectorAll(".jobs-table-viewport").forEach(function (vp) {
    var s = scrollState.get(vp.dataset.scrollkey);
    if (s) {
      vp.scrollLeft = s.left;
      vp.scrollTop = s.top;
    }
  });
}

function classify(w) {
  var stale =
    (w.status === 0 || w.status === 1) && w.hb_age_s > HEARTBEAT_EXPIRY_S;
  if (w.status === 3)
    return { label: "down (exited)", cls: "s-exited", stale: false };
  if (stale)
    return { label: "down (presumed)", cls: "s-down", stale: true };
  if (w.status === 2)
    return { label: "stopping", cls: "s-stopping", stale: false };
  if (w.status === 1)
    return { label: "running", cls: "s-running", stale: false };
  return { label: "idle", cls: "s-idle", stale: false };
}

function drow(dl, k, v) {
  dl.appendChild(el("dt", null, k));
  dl.appendChild(el("dd", null, v));
}

function workerCell(w) {
  var s = classify(w);
  var cell = el("div", "cell " + s.cls + (s.stale ? " stale" : ""));
  cell.appendChild(el("div", "st", s.label));
  cell.appendChild(el("div", "id", w.worker_id));
  if (w.current_job)
    cell.appendChild(el("div", "job", "job: " + w.current_job));
  else cell.appendChild(el("div", "job none", "no job"));
  var details = el("div", "details");
  var dl = el("dl");
  drow(dl, "worker", w.worker_id);
  drow(dl, "state", s.label);
  drow(dl, "current job", w.current_job || "\u2014");
  drow(dl, "user", w.user_id || "\u2014");
  drow(dl, "completed", String(w.jobs_completed));
  drow(
    dl,
    "heartbeat",
    w.hb_age_s + "s ago" + (s.stale ? "  (STALE)" : ""),
  );
  drow(dl, "pod", w.argo_pod_name || "\u2014");
  details.appendChild(dl);
  cell.appendChild(details);
  return cell;
}

function spawnCell(sp) {
  var cell = el("div", "cell s-starting");
  cell.appendChild(el("div", "st", "starting"));
  cell.appendChild(el("div", "id", "(registering\u2026)"));
  cell.appendChild(el("div", "job none", sp.language_hint || "worker"));
  var details = el("div", "details");
  var dl = el("dl");
  drow(dl, "state", "starting (pending spawn)");
  drow(dl, "workflow", sp.workflow_uid);
  drow(dl, "language", sp.language_hint || "\u2014");
  drow(dl, "spawned", sp.age_s + "s ago");
  details.appendChild(dl);
  cell.appendChild(details);
  return cell;
}

function* renderWorkersSteps(workers, spawns) {
  var host = document.getElementById("workers");
  var fragment = document.createDocumentFragment();
  for (var sp of spawns || []) {
    fragment.appendChild(spawnCell(sp));
    yield;
  }
  for (var w of workers || []) {
    fragment.appendChild(workerCell(w));
    yield;
  }
  if (!fragment.children.length)
    fragment.appendChild(el("div", "empty", "no workers"));
  host.replaceChildren(fragment);
}

function* renderSteps(data) {
  if (typeof data.heartbeat_expiry_s === "number")
    HEARTBEAT_EXPIRY_S = data.heartbeat_expiry_s;
  yield* renderJobsSteps(data.jobs || []);
  yield* renderWorkersSteps(data.workers || [], data.spawns || []);
  var meta = document.getElementById("meta");
  meta.textContent =
    "updated " +
    (data.generated_at || "?") +
    "  \u00b7  refresh " +
    data.refresh_ms / 1000 +
    "s" +
    "  \u00b7  " +
    (data.servers ? data.servers.length : data.server ? 1 : 0) +
    " servers, " +
    (data.jobs ? data.jobs.length : 0) +
    " jobs, " +
    (data.workers ? data.workers.length : 0) +
    " workers, " +
    (data.spawns ? data.spawns.length : 0) +
    " starting";
  if (data.error) {
    meta.appendChild(el("span", "err", "  \u00b7  error: " + data.error));
  }
  renderServers(data.servers || [], data.served_by || "", data.server || null);
}

// Replay drains synchronously; the live driver yields between bounded batches.
function render(data) {
  for (var step of renderSteps(data)) { /* drain */ }
}
