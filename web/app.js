const LANE_W = 14;
const ROW_H = 28;
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

function graphSvg(commit, prev, laneCount) {
  const n = Math.max(laneCount, commit.lane + 1);
  const w = n * LANE_W + 10;
  const h = ROW_H;
  const x = (lane) => 8 + lane * LANE_W;
  const mid = h / 2;
  const parts = [];
  const through = new Set(commit.through || []);
  const prevThrough = new Set(prev ? prev.through || [] : []);
  const active = new Set([...through, ...prevThrough, commit.lane, ...(commit.joins || [])]);
  if (prev) {
    for (const e of prev.edges || []) {
      active.add(e.from_lane);
      active.add(e.to_lane);
    }
  }

  for (const lane of active) {
    const stroke = color(lane);
    parts.push(
      `<line x1="${x(lane)}" y1="0" x2="${x(lane)}" y2="${h}" stroke="${stroke}" stroke-width="2"/>`
    );
  }

  if (prev) {
    for (const e of prev.edges || []) {
      if (e.from_lane === e.to_lane) continue;
      const stroke = color(e.kind === "merge" ? e.to_lane : e.from_lane);
      parts.push(
        `<path d="M ${x(e.from_lane)} 0 C ${x(e.from_lane)} ${mid}, ${x(e.to_lane)} ${mid}, ${x(e.to_lane)} ${h}" fill="none" stroke="${stroke}" stroke-width="2"/>`
      );
    }
  }

  for (const j of commit.joins || []) {
    const stroke = color(j);
    parts.push(
      `<path d="M ${x(j)} 0 C ${x(j)} ${mid}, ${x(commit.lane)} ${mid}, ${x(commit.lane)} ${mid}" fill="none" stroke="${stroke}" stroke-width="2"/>`
    );
  }

  const cx = x(commit.lane);
  const fill = commit.uncommitted ? "transparent" : color(commit.lane);
  const stroke = color(commit.lane);
  parts.push(
    `<circle cx="${cx}" cy="${mid}" r="4.5" fill="${fill}" stroke="${stroke}" stroke-width="2"/>`
  );
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true">${parts.join("")}</svg>`;
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
  document.documentElement.style.setProperty("--graph-w", `${Math.max(72, laneCount * LANE_W + 16)}px`);
  state.commits.forEach((c, i) => {
    const prev = i > 0 ? state.commits[i - 1] : null;
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
      <div class="col-graph graph-cell">${graphSvg(c, prev, laneCount)}</div>
      <div class="col-desc">${extra}${esc(c.subject || "")}</div>
      <div class="col-date">${c.uncommitted ? "" : relTime(c.author_at)}</div>
      <div class="col-author">${esc(c.author || "")}</div>
      <div class="col-hash">${c.uncommitted ? "" : (c.hash || "").slice(0, 8)}</div>
    `;
    row.addEventListener("click", () => selectCommit(c.hash));
    wrap.appendChild(row);
  });
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
