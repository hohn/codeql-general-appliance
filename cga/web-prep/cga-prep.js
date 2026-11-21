// Read-only composite view for the independent CGA preparation session.
const DEFAULTS = {
  cgacv: "http://127.0.0.1:8501",
  cgasp: "http://127.0.0.1:8502",
  cgadb: "http://127.0.0.1:8503",
  cgaqg: "http://127.0.0.1:8504",
};
const CONFIG = Object.assign({}, DEFAULTS, window.CGA_PREP_CONFIG || {});

function baseFor(comp) {
  return CONFIG[comp] || DEFAULTS[comp];
}

async function fetchFragment(comp, route) {
  const resp = await fetch(baseFor(comp) + route, { cache: "no-store" });
  if (!resp.ok) throw new Error(`${comp}${route}: HTTP ${resp.status}`);
  return await resp.text();
}

async function loadSlot(el) {
  const comp = el.dataset.comp;
  const route = el.dataset.route;
  try {
    el.innerHTML = await fetchFragment(comp, route);
  } catch (error) {
    el.innerHTML = `<div class="cga-err">${comp} unavailable: ${String(error.message || error)}</div>`;
  }
}

let selectedDetail = "cgacv";

async function refreshAll() {
  const overview = Array.from(document.querySelectorAll(".cga-box[data-comp]"));
  await Promise.all(overview.map(loadSlot));
  const detail = document.getElementById("cga-detail");
  detail.dataset.comp = selectedDetail;
  detail.dataset.route = "/detail";
  document.getElementById("cga-detail-which").textContent = selectedDetail;
  await loadSlot(detail);
}

document
  .getElementById("cga-flow-preparation")
  .addEventListener("click", async (event) => {
    const box = event.target.closest(".cga-box[data-comp]");
    if (box) {
      selectedDetail = box.dataset.comp;
      await refreshAll();
    }
  });
document.getElementById("cga-reload").addEventListener("click", refreshAll);
refreshAll();
