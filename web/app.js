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
  ghWait: null,
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

function mergeRuns(runs) {
  const sorted = runs.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const out = [];
  for (const [a, b] of sorted) {
    if (!out.length || a > out[out.length - 1][1] + 0.01) {
      out.push([a, b]);
    } else {
      out[out.length - 1][1] = Math.max(out[out.length - 1][1], b);
    }
  }
  return out;
}

function drawGraph(commits, laneCount) {
  const canvas = $("graphOverlay");
  if (!canvas) return;
  const n = Math.max(laneCount || 1, 1);
  const w = Math.max(72, n * LANE_W + LANE_PAD * 2);
  const h = Math.max(commits.length, 1) * ROW_H;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  canvas.style.width = w + "px";
  canvas.style.height = h + "px";
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#1c1c1c";
  ctx.fillRect(0, 0, w, h);
  ctx.lineWidth = 2;
  ctx.lineJoin = "round";

  const verts = new Map();
  function addVert(lane, y1, y2) {
    if (y1 === y2) return;
    if (!verts.has(lane)) verts.set(lane, []);
    verts.get(lane).push([Math.min(y1, y2), Math.max(y1, y2)]);
  }

  function strokePipe(x1, y1, x2, y2, stroke, cap) {
    ctx.strokeStyle = stroke;
    ctx.lineCap = cap;
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    if (x1 === x2) {
      ctx.lineTo(x2, y2);
    } else {
      const dy = y2 - y1;
      const bend = Math.min(Math.abs(dy) * 0.4, Math.abs(x2 - x1), 12);
      ctx.bezierCurveTo(x1, y1 + bend, x2, y2 - bend, x2, y2);
    }
    ctx.stroke();
  }

  for (let i = 0; i < commits.length - 1; i++) {
    const prev = commits[i];
    const curr = commits[i + 1];
    const y1 = rowMid(i);
    const y2 = rowMid(i + 1);
    const joinSet = new Set(curr.joins || []);
    const drawnFrom = new Set();
    const takenDest = new Set();

    for (const e of prev.edges || []) {
      const from = e.from_lane;
      const to = e.to_lane;
      if (joinSet.has(from)) {
        strokePipe(
          laneX(from),
          y1,
          laneX(curr.lane),
          y2,
          color(from),
          "round"
        );
        drawnFrom.add(from);
        continue;
      }
      const stroke = color(e.kind === "merge" ? to : from);
      if (from === to) {
        addVert(from, y1, y2);
      } else {
        strokePipe(laneX(from), y1, laneX(to), y2, stroke, "round");
        takenDest.add(to);
      }
      drawnFrom.add(from);
    }
    for (const j of curr.joins || []) {
      if (drawnFrom.has(j)) continue;
      strokePipe(laneX(j), y1, laneX(curr.lane), y2, color(j), "round");
      drawnFrom.add(j);
    }
    for (const lane of prev.through || []) {
      if (drawnFrom.has(lane) || takenDest.has(lane) || joinSet.has(lane)) {
        continue;
      }
      addVert(lane, y1, y2);
    }
  }

  for (const [lane, runs] of verts) {
    for (const [y1, y2] of mergeRuns(runs)) {
      strokePipe(laneX(lane), y1, laneX(lane), y2, color(lane), "butt");
    }
  }

  for (let i = 0; i < commits.length; i++) {
    const c = commits[i];
    const cx = laneX(c.lane);
    const cy = rowMid(i);
    const stroke = color(c.lane);
    ctx.beginPath();
    ctx.arc(cx, cy, 4, 0, Math.PI * 2);
    ctx.fillStyle = c.uncommitted ? "#1c1c1c" : stroke;
    ctx.strokeStyle = stroke;
    ctx.lineWidth = 2;
    ctx.lineCap = "butt";
    ctx.fill();
    ctx.stroke();
  }
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

async function maybeFetchRemote() {
  if (!state.repoId) return;
  const st = await api("/api/github/status");
  if (!st.logged_in) return;
  $("headLabel").textContent = "Fetching...";
  await api("/api/github/fetch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: state.repoId }),
  });
}

async function refreshView(fetchRemote) {
  if (state.loading) return;
  state.loading = true;
  showError("");
  try {
    if (fetchRemote) await maybeFetchRemote();
  } catch (err) {
    showError(String(err.message || err));
  } finally {
    state.loading = false;
  }
  await loadGraph(true);
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

function markSelected(hash) {
  state.selected = hash || "";
  const rows = $("rows");
  if (!rows) return;
  for (const row of rows.children) {
    row.classList.toggle("selected", row.dataset.hash === state.selected);
  }
}

function hideDetail() {
  $("detail").classList.add("hidden");
  markSelected("");
}

async function selectCommit(hash) {
  markSelected(hash);
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
    if (data.repo && data.repo.id) {
      state.repoId = data.repo.id;
      $("repoSelect").value = state.repoId;
    }
    await refreshView(true);
  } catch (err) {
    showError(String(err.message || err));
  }
}

async function findRepos() {
  showError("");
  const buttons = ["scanBtn", "emptyScanBtn"].map($).filter(Boolean);
  for (const btn of buttons) btn.disabled = true;
  try {
    const data = await api("/api/repos/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    await loadRepos();
    if (data.repo && data.repo.id) {
      state.repoId = data.repo.id;
      $("repoSelect").value = state.repoId;
    }
    await refreshView(true);
  } catch (err) {
    showError(String(err.message || err));
  } finally {
    for (const btn of buttons) btn.disabled = false;
  }
}

function showGhCode(code, uri) {
  const wrap = $("ghCodeWrap");
  const el = $("ghCode");
  if (code) {
    el.textContent = code;
    wrap.classList.remove("hidden");
    $("ghHint").textContent =
      "Type this code on GitHub, then come back. A browser window should have opened (" +
      (uri || "github.com/login/device") +
      ").";
  } else {
    el.textContent = "";
    wrap.classList.add("hidden");
  }
}

function renderGhStatus(st) {
  const label = $("ghStatus");
  const loginBtn = $("ghLoginBtn");
  const logoutBtn = $("ghLogoutBtn");
  const header = $("ghBtn");
  if (!st.gh_ok) {
    label.textContent = "GitHub CLI not found";
    loginBtn.classList.add("hidden");
    logoutBtn.classList.add("hidden");
    header.textContent = "GitHub";
    showGhCode("", "");
    $("ghHint").textContent = "Install gh from " + (st.install_url || "https://cli.github.com/");
    return;
  }
  if (st.logged_in) {
    label.textContent = "GitHub: " + st.user;
    loginBtn.classList.add("hidden");
    logoutBtn.classList.remove("hidden");
    header.textContent = "@" + st.user;
    showGhCode("", "");
    $("ghHint").textContent =
      "Signed in as " +
      st.user +
      ". Saved on this PC until Sign out. Click a row to open or add.";
  } else {
    label.textContent = "GitHub: signed out";
    loginBtn.classList.remove("hidden");
    logoutBtn.classList.add("hidden");
    header.textContent = "GitHub";
    showGhCode(st.user_code || "", st.verification_uri || "");
  }
}

function renderGhList(data) {
  const box = $("ghList");
  box.innerHTML = "";
  const repos = data.repos || [];
  if (!repos.length) {
    box.textContent = data.logged_in ? "No GitHub repos returned." : "";
    return;
  }
  for (const r of repos) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "gh-row";
    const localId = r.local && r.local.id ? r.local.id : "";
    if (localId && localId === state.repoId) {
      row.classList.add("current");
      row.setAttribute("aria-current", "true");
    }
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = r.nameWithOwner || r.name;
    row.appendChild(name);
    if (r.private) {
      const p = document.createElement("span");
      p.className = "pill remote";
      p.textContent = "private";
      row.appendChild(p);
    }
    const action = document.createElement("span");
    action.className = "action";
    action.textContent = localId ? "Open" : "Add";
    row.appendChild(action);
    row.addEventListener("click", async () => {
      if (localId) {
        await openGithubLocal(localId);
      } else {
        await cloneGithub(r.nameWithOwner, row);
      }
    });
    box.appendChild(row);
  }
}

async function openGithubLocal(id) {
  showError("");
  try {
    await api("/api/repos/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    state.repoId = id;
    $("repoSelect").value = state.repoId;
    await refreshView(true);
    await refreshGithub(true);
  } catch (err) {
    showError(String(err.message || err));
  }
}

async function refreshGithub(loadList) {
  const st = await api("/api/github/status");
  renderGhStatus(st);
  if (loadList && st.logged_in) {
    const data = await api("/api/github/repos");
    renderGhStatus(data);
    renderGhList(data);
  } else if (!st.logged_in) {
    $("ghList").innerHTML = "";
    if (st.gh_ok && !st.user_code) {
      $("ghHint").textContent =
        "Sign in to list your GitHub repos and add missing clones. The graph itself stays local.";
    }
  }
}

async function openGithubPanel() {
  $("ghPanel").classList.remove("hidden");
  showError("");
  try {
    await refreshGithub(true);
  } catch (err) {
    showError(String(err.message || err));
  }
}

async function githubLogin() {
  showError("");
  try {
    const data = await api("/api/github/login", { method: "POST" });
    if (data.already) {
      await refreshGithub(true);
      return;
    }
    showGhCode(data.user_code || "", data.verification_uri || "");
    if (!data.user_code) {
      $("ghHint").textContent = "Starting GitHub sign-in...";
    }
    if (state.ghWait) clearInterval(state.ghWait);
    let n = 0;
    state.ghWait = setInterval(async () => {
      n += 1;
      try {
        const st = await api("/api/github/status");
        renderGhStatus(st);
        if (st.logged_in) {
          clearInterval(state.ghWait);
          state.ghWait = null;
          await refreshGithub(true);
        } else if (n > 90) {
          clearInterval(state.ghWait);
          state.ghWait = null;
        }
      } catch (_) {
        /* keep polling */
      }
    }, 2000);
  } catch (err) {
    showError(String(err.message || err));
  }
}

async function cloneGithub(nwo, btn) {
  showError("");
  if (btn) btn.disabled = true;
  try {
    const data = await api("/api/github/clone", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nameWithOwner: nwo }),
    });
    await loadRepos();
    if (data.repo && data.repo.id) {
      state.repoId = data.repo.id;
      $("repoSelect").value = state.repoId;
    }
    await refreshGithub(true);
    await refreshView(true);
  } catch (err) {
    showError(String(err.message || err));
  } finally {
    if (btn) btn.disabled = false;
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

async function githubLogout() {
  showError("");
  try {
    await api("/api/github/logout", { method: "POST" });
    if (state.ghWait) {
      clearInterval(state.ghWait);
      state.ghWait = null;
    }
    await refreshGithub(true);
  } catch (err) {
    showError(String(err.message || err));
  }
}

async function githubFetch() {
  if (!state.repoId) {
    showError("Open a local repo first");
    return;
  }
  $("ghFetchBtn").disabled = true;
  try {
    await refreshView(true);
  } finally {
    $("ghFetchBtn").disabled = false;
  }
}

$("openBtn").addEventListener("click", openFolder);
$("scanBtn").addEventListener("click", findRepos);
$("emptyOpenBtn").addEventListener("click", openFolder);
$("emptyScanBtn").addEventListener("click", findRepos);
$("ghBtn").addEventListener("click", openGithubPanel);
$("emptyGhBtn").addEventListener("click", () => {
  openGithubPanel();
  githubLogin();
});
$("ghLoginBtn").addEventListener("click", githubLogin);
$("ghOpenDeviceBtn").addEventListener("click", async () => {
  try {
    await api("/api/github/open", { method: "POST" });
  } catch (err) {
    showError(String(err.message || err));
  }
});
$("ghLogoutBtn").addEventListener("click", githubLogout);
$("ghFetchBtn").addEventListener("click", githubFetch);
$("ghCloseBtn").addEventListener("click", () => $("ghPanel").classList.add("hidden"));
$("refreshBtn").addEventListener("click", () => refreshView(true));
$("quitBtn").addEventListener("click", quit);
$("moreBtn").addEventListener("click", () => loadGraph(false));
$("detailClose").addEventListener("click", hideDetail);
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
    await refreshView(true);
  } catch (err) {
    showError(String(err.message || err));
  }
});

document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") {
    hideDetail();
    return;
  }
  if (ev.ctrlKey && ev.key.toLowerCase() === "r") {
    ev.preventDefault();
    refreshView(true);
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
    refreshGithub(false).catch(() => {});
    await loadRepos();
    if (!state.repos.length) {
      await findRepos();
      return;
    }
    state.repoId = state.lastOpened || "";
    await refreshView(true);
  } catch (err) {
    showError(String(err.message || err));
  }
})();
