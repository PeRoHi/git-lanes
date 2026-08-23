const LANE_W = 16;
const ROW_H = 28;
const LANE_PAD = 8;
const COLORS = [
  "#3db9d3",
  "#c86cc8",
  "#8fbb55",
  "#e0c05c",
  "#e05656",
  "#6cb6de",
  "#d0894a",
  "#9b8fd4",
  "#5dcea6",
  "#e07aa2",
];

const state = {
  repos: [],
  lastOpened: "",
  repoId: "",
  commits: [],
  hasMore: false,
  laneCount: 1,
  selected: "",
  loading: false,
};

const $ = (id) => document.getElementById(id);

function color(i) {
  return COLORS[i % COLORS.length];
}

function relTime(ts) {
  if (!ts) return "";
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 60) return "just now";
  if (s < 3600) return Math.floor(s / 60) + " minutes ago";
  if (s < 86400) return Math.floor(s / 3600) + " hours ago";
  if (s < 86400 * 14) return Math.floor(s / 86400) + " days ago";
  const d = new Date(ts * 1000);
  return d.toISOString().slice(0, 10);
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function pillClass(ref) {
  if (ref.startsWith("HEAD")) return "head";
  if (ref.startsWith("tag:")) return "tag";
  if (ref.includes("/")) return "remote";
  return "branch";
}

function linkify(text) {
  const esc = (s) =>
    s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  return esc(text).replace(
    /https?:\/\/[^\s<]+/g,
    (u) => `<a href="${u}" target="_blank" rel="noopener">${u}</a>`
  );
}

function laneX(lane) {
  return LANE_PAD + lane * LANE_W;
}

function rowMid(i) {
  return i * ROW_H + ROW_H / 2;
}

function pipe(x1, y1, x2, y2) {
  if (x1 === x2) {
    return `M ${x1} ${y1} V ${y2}`;
  }
  const dy = y2 - y1;
  const bend = Math.min(Math.abs(dy) * 0.45, Math.abs(x2 - x1) * 0.85, 14);
  return `M ${x1} ${y1} C ${x1} ${y1 + bend}, ${x2} ${y2 - bend}, ${x2} ${y2}`;
}

function drawGraph(commits, laneCount) {
  const svg = $("graphOverlay");
  if (!svg) return;
  const n = Math.max(laneCount || 1, 1);
  const w = n * LANE_W + LANE_PAD * 2;
  const h = Math.max(commits.length, 1) * ROW_H;
  const parts = [];
  const strokeAttr = 'fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';

  for (let i = 0; i < commits.length - 1; i++) {
    const prev = commits[i];
    const curr = commits[i + 1];
    const y1 = rowMid(i);
    const y2 = rowMid(i + 1);
    const drawnFrom = new Set();
    const takenDest = new Set();

    for (const e of prev.edges || []) {
      const from = e.from_lane;
      const to = e.to_lane;
      const stroke = color(e.kind === "merge" ? to : from);
      parts.push(`<path d="${pipe(laneX(from), y1, laneX(to), y2)}" stroke="${stroke}" ${strokeAttr}/>`);
      drawnFrom.add(from);
      if (from !== to) takenDest.add(to);
    }
    for (const j of curr.joins || []) {
      if (drawnFrom.has(j)) continue;
      parts.push(
        `<path d="${pipe(laneX(j), y1, laneX(curr.lane), y2)}" stroke="${color(j)}" ${strokeAttr}/>`
      );
      drawnFrom.add(j);
    }
    for (const lane of prev.through || []) {
      if (drawnFrom.has(lane) || takenDest.has(lane)) continue;
      parts.push(
        `<path d="${pipe(laneX(lane), y1, laneX(lane), y2)}" stroke="${color(lane)}" ${strokeAttr}/>`
      );
    }
  }

  for (let i = 0; i < commits.length; i++) {
    const c = commits[i];
    const cx = laneX(c.lane);
    const cy = rowMid(i);
    const stroke = color(c.lane);
    const fill = c.uncommitted ? "#1c1c1c" : stroke;
    parts.push(
      `<circle cx="${cx}" cy="${cy}" r="4" fill="${fill}" stroke="${stroke}" stroke-width="2"/>`
    );
  }

  svg.setAttribute("width", String(w));
  svg.setAttribute("height", String(h));
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.setAttribute("shape-rendering", "geometricPrecision");
  svg.innerHTML = parts.join("");
}

function renderRepos() {
  const sel = $("repoSelect");
  sel.innerHTML = "";
  const ph = document.createElement("option");
  ph.value = "";
  ph.textContent = state.repos.length ? "Select repo" : "No repos yet";
  sel.appendChild(ph);
  for (const r of state.repos) {
    const o = document.createElement("option");
    o.value = r.id;
    o.textContent = r.name;
    sel.appendChild(o);
  }
  sel.value = state.repoId || state.lastOpened || "";
}

function renderRows() {
  const wrap = $("rows");
  wrap.innerHTML = "";
  const laneCount = state.laneCount || 1;
  document.documentElement.style.setProperty(
    "--graph-w",
    `${Math.max(72, laneCount * LANE_W + LANE_PAD * 2)}px`
  );
  state.commits.forEach((c) => {
    const row = document.createElement("div");
    row.className = "row" + (c.hash === state.selected ? " selected" : "");
    row.dataset.hash = c.hash;
    const refs = (c.refs || [])
      .map((r) => `<span class="pill ${pillClass(r)}">${esc(r.replace(/^tag: /, ""))}</span>`)
      .join("");
    const extra = c.uncommitted
      ? `<span class="pill uncommitted">Uncommitted</span>`
      : refs;
    row.innerHTML = `
      <div class="col-graph graph-cell"></div>
      <div class="col-desc">${extra}${esc(c.subject || "")}</div>
      <div class="col-date">${c.uncommitted ? "" : relTime(c.author_at)}</div>
      <div class="col-author">${esc(c.author || "")}</div>
      <div class="col-hash">${c.uncommitted ? "" : (c.hash || "").slice(0, 8)}</div>
    `;
    row.addEventListener("click", () => selectCommit(c.hash));
    wrap.appendChild(row);
  });
  drawGraph(state.commits, laneCount);
  $("moreBtn").classList.toggle("hidden", !state.hasMore);
}

async function api(url, opts) {
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function showError(msg) {
  const el = $("error");
  if (!msg) {
    el.classList.add("hidden");
    el.textContent = "";
    return;
  }
  el.textContent = msg;
  el.classList.remove("hidden");
}

async function loadRepos() {
  const data = await api("/api/repos");
  state.repos = data.repos || [];
  state.lastOpened = data.last_opened || "";
  renderRepos();
}

async function loadGraph(reset) {
  if (state.loading) return;
  state.loading = true;
  showError("");
  try {
    const offset = reset ? 0 : state.commits.filter((c) => !c.uncommitted).length;
    const q = new URLSearchParams();
    if (state.repoId) q.set("repo_id", state.repoId);
    q.set("offset", String(reset ? 0 : offset));
    q.set("limit", "300");
    const data = await api("/api/graph?" + q.toString());
    if (data.need_open) {
      $("tableWrap").classList.add("hidden");
      $("empty").classList.remove("hidden");
      $("headLabel").textContent = "";
      return;
    }
    $("empty").classList.add("hidden");
    $("tableWrap").classList.remove("hidden");
    if (data.repo) {
      state.repoId = data.repo.id;
      $("repoSelect").value = state.repoId;
      $("headLabel").textContent = data.repo.head ? "HEAD " + data.repo.head : "";
    }
    if (reset) {
      state.commits = data.commits || [];
      state.selected = "";
      $("detail").classList.add("hidden");
    } else {
      state.commits = state.commits.concat(data.commits || []);
    }
    state.hasMore = !!data.has_more;
    state.laneCount = data.lane_count || 1;
    renderRows();
  } catch (err) {
    showError(String(err.message || err));
    $("tableWrap").classList.add("hidden");
    $("empty").classList.add("hidden");
  } finally {
    state.loading = false;
  }
}

async function selectCommit(hash) {
  state.selected = hash;
  renderRows();
  try {
    const q = new URLSearchParams({ repo_id: state.repoId, hash });
    const data = await api("/api/commit?" + q.toString());
    const refs = (data.refs || []).join(", ");
    const parents = (data.parents || []).map((p) => p.slice(0, 8)).join(", ");
    $("detailBody").innerHTML = `
      <h2>${linkify(data.subject || "")}</h2>
      <div class="kv"><b>Commit</b> ${data.uncommitted ? "uncommitted" : data.hash}</div>
      <div class="kv"><b>Author</b> ${data.author || "-"}</div>
      <div class="kv"><b>Parents</b> ${parents || "-"}</div>
      <div class="kv"><b>Refs</b> ${refs || "-"}</div>
      <pre>${linkify(data.body || "")}</pre>
    `;
    $("detail").classList.remove("hidden");
  } catch (err) {
    showError(String(err.message || err));
  }
}

function scrollToHead() {
  const i = state.commits.findIndex((c) =>
    (c.refs || []).some((r) => r.startsWith("HEAD"))
  );
  if (i < 0) return;
  const rows = $("rows").children;
  if (rows[i]) rows[i].scrollIntoView({ block: "center" });
  selectCommit(state.commits[i].hash);
}

async function openFolder() {
  showError("");
  try {
    const data = await api("/api/repos/browse", { method: "POST" });
    if (data.cancelled) return;
    await loadRepos();
    state.repoId = data.repo.id;
    $("repoSelect").value = state.repoId;
    await loadGraph(true);
  } catch (err) {
    showError(String(err.message || err));
  }
}

async function quit() {
  try {
    await api("/api/shutdown", { method: "POST" });
  } catch (_) {
    /* ignore */
  }
  window.close();
}

$("openBtn").addEventListener("click", openFolder);
$("emptyOpenBtn").addEventListener("click", openFolder);
$("refreshBtn").addEventListener("click", () => loadGraph(true));
$("quitBtn").addEventListener("click", quit);
$("moreBtn").addEventListener("click", () => loadGraph(false));
$("detailClose").addEventListener("click", () => {
  $("detail").classList.add("hidden");
  state.selected = "";
  renderRows();
});
$("repoSelect").addEventListener("change", async (ev) => {
  const id = ev.target.value;
  if (!id) return;
  try {
    await api("/api/repos/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    state.repoId = id;
    await loadGraph(true);
  } catch (err) {
    showError(String(err.message || err));
  }
});

document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") {
    $("detail").classList.add("hidden");
    return;
  }
  if (ev.ctrlKey && ev.key.toLowerCase() === "r") {
    ev.preventDefault();
    loadGraph(true);
  }
  if (ev.ctrlKey && ev.key.toLowerCase() === "h") {
    ev.preventDefault();
    scrollToHead();
  }
});

window.addEventListener("pagehide", () => {
  navigator.sendBeacon("/api/shutdown", "");
});

(async function init() {
  try {
    await loadRepos();
    state.repoId = state.lastOpened || "";
    await loadGraph(true);
  } catch (err) {
    showError(String(err.message || err));
  }
})();
