const esc = value => String(value ?? "").replace(/[&<>"']/g, c =>
  ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const when = value => value ? new Date(value).toLocaleString() : "";

async function refresh() {
  try {
    const response = await fetch("/api/snapshot", {cache:"no-store"});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    document.querySelector("#updated").textContent = `updated ${when(data.generated_at)}`;
    const campaignCounts = Object.entries(data.dispositions || {}).map(
      ([key,value]) => [`campaign: ${key}`, value]);
    document.querySelector("#counts").innerHTML = Object.entries(data.counts || {}).concat(campaignCounts)
      .sort().map(([key,value]) => `<div class="card ${esc(key)}"><span>${esc(key)}</span><strong>${value}</strong></div>`).join("");
    document.querySelector("#builders").innerHTML = (data.builders || []).map(b =>
      `<div class="card"><span>${esc(b.builder_id)}</span><strong class="${esc(b.phase)}">${esc(b.phase || "idle")}</strong><small class="muted">${esc(b.current_job || "no job")}</small></div>`).join("") ||
      '<span class="muted">No registered builders.</span>';
    document.querySelector("#jobs tbody").innerHTML = (data.jobs || []).map(j =>
      `<tr><td>${esc(j.cve)}</td><td>${esc(j.package)}</td><td>${esc(j.variant)}</td><td>${esc(j.mode)}</td><td>${esc(j.lane)}</td><td class="${esc(j.status)}">${esc(j.status)}</td><td>${esc(j.disposition)}</td><td>${esc(j.promotion_status)}</td><td>${esc(j.failure_reason || j.promotion_error)}</td><td>${j.resource_report_url ? `<a href="${esc(j.resource_report_url)}">report</a>` : ""}</td><td>${esc(j.claimed_by)}</td><td>${j.attempt_count}</td><td>${when(j.updated_at)}</td></tr>`).join("");
  } catch (error) {
    document.querySelector("#updated").textContent = `unavailable: ${error.message}`;
  }
}
refresh();
setInterval(refresh, 2000);
