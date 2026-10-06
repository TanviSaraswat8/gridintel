// GridIntel web — boot, auth, router, replay polling, command palette, keyboard shortcuts.
import { API, S, api, color, confirmDialog, destroyCharts, errorState, esc, logout, toast, ts } from "./core.js";
import * as V from "./views.js";

const $ = (q) => document.querySelector(q);
const ROUTES = { command: ["Command Center", V.command], scada: ["SCADA Live", V.scada], digital: ["Digital Substation", V.digital],
  investigate: ["Investigation", V.investigate], fleet: ["Fleet Intelligence", V.fleet], analytics: ["Analytics", V.analytics],
  models: ["AI Model Lab", V.models], explorer: ["Data Explorer", V.explorer] };
const LIVE = new Set(["command", "scada", "digital", "fleet"]);
let busy = false, lastKey = "";

// ------------------------------------------------------------------------------------- auth
$("#loginForm").onsubmit = async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  $("#loginErr").textContent = "";
  try {
    const r = await api("/auth/login", { method: "POST", body: { username: f.get("username"), password: f.get("password") } });
    S.token = r.access_token; S.user = r.user;
    sessionStorage.setItem("gi_token", r.access_token); sessionStorage.setItem("gi_user", JSON.stringify(r.user));
    start();
  } catch (err) { $("#loginErr").textContent = err.message; }
};
$("#logout").onclick = () => logout();

// ------------------------------------------------------------------------------------- first-run setup (hosted deployments)
// A hosted instance starts in AWAITING DATA mode: no private workbooks, no models. An ADMIN uploads the artifact
// bundle made by scripts/package_artifacts.py (model artifacts + derived values; verbatim Excel cells are stripped).
function showSetup() {
  $("#shell").hidden = true; $("#login").hidden = false;
  $("#loginForm").innerHTML = `<a class="logo" href="/"><img src="/assets/img/mark.svg" alt="" /><span data-noi18n>GRID<b>INTEL</b></span></a>
    <h1>Awaiting data</h1>
    <p class="dim">This deployment has no model artifacts yet. Upload the bundle file <span class="mono">gridintel-artifacts.tar.gz</span> made on the local machine with <span class="mono">python scripts/package_artifacts.py</span>.</p>
    <label>Artifact bundle<input type="file" id="bundleFile" accept=".gz,.tgz,application/gzip" required /></label>
    <div class="err" id="loginErr" role="alert"></div>
    <button class="btn btn-primary" type="submit" id="bundleBtn">Upload and load models</button>
    <button class="btn btn-ghost btn-sm" type="button" id="setupOut">Sign out</button>
    <p class="faint tiny">PUBLIC DEMO MODE · the private HVPNL Excel files are never uploaded.</p>`;
  $("#setupOut").onclick = () => { logout(); location.reload(); };
  $("#loginForm").onsubmit = async (e) => {
    e.preventDefault();
    const f = $("#bundleFile").files[0]; if (!f) return;
    $("#bundleBtn").disabled = true; $("#loginErr").textContent = "Uploading…";
    try {
      const r = await fetch(API + "/admin/artifacts", { method: "POST", headers: { Authorization: "Bearer " + S.token, "Content-Type": "application/gzip" }, body: f });
      const j = await r.json();
      if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail));
      $("#loginErr").textContent = `Loaded: ${j.substations_with_data} substations with readings. Opening the Command Center…`;
      setTimeout(() => location.reload(), 1200);
    } catch (err) { $("#loginErr").textContent = err.message; $("#bundleBtn").disabled = false; }
  };
}

// ------------------------------------------------------------------------------------- boot
async function start() {
  try {
    const subs = await api("/substations");
    S.subs = subs.items;
  } catch (e) {
    if (e.status === 401) return;
    if (e.status === 503 && S.user?.role === "ADMIN") return showSetup();
    $("#login").hidden = false; $("#loginErr").textContent = e.message; return;
  }
  $("#login").hidden = true; $("#shell").hidden = false;
  $("#user").textContent = `${S.user.username} · ${S.user.role}`;
  fetch(API.replace(/\/api\/v1$/, "") + "/health").then((r) => r.json()).then((h) => {
    const m = $("#dataMode"); if (!m || !h.data_mode) return;
    m.textContent = h.data_mode; m.hidden = false; m.classList.toggle("public", h.data_mode.startsWith("PUBLIC"));
  }).catch(() => {});
  if (!S.subs.find((s) => s.id === S.sid && s.has_model)) S.sid = "220-sec-46";
  $("#subSel").innerHTML = `<optgroup label="With source readings">${S.subs.filter((s) => s.has_model).map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join("")}</optgroup>
    <optgroup label="No source readings">${S.subs.filter((s) => !s.has_model).map((s) => `<option value="${s.id}">${esc(s.name)} — no data</option>`).join("")}</optgroup>`;
  $("#subSel").value = S.sid;
  $("#subSel").onchange = (e) => selectSub(e.target.value);
  const st = await api("/replay/status");
  $("#dateSel").innerHTML = `<option value="">All dates</option>` + st.dates.map((d) => `<option value="${d}">${d}</option>`).join("");
  $("#dateSel").onchange = (e) => e.target.value && control("seek", { timestamp: e.target.value + "T00:00:00" });
  document.querySelectorAll("#replayCtl [data-act]").forEach((b) => (b.onclick = () => control(b.dataset.act)));
  document.querySelectorAll("#speed [data-s]").forEach((b) => (b.onclick = () => control("speed", { speed: +b.dataset.s })));
  const isOp = ["OPERATOR", "ENGINEER", "ADMIN"].includes(S.user.role);
  document.querySelectorAll("#replayCtl button").forEach((b) => { b.disabled = !isOp; if (!isOp) b.title = "Requires OPERATOR role"; });
  const al = await api("/alerts", { params: { size: 1 } });
  S.lastAlert = al.items[0]?.id || 0;
  applyStatus(st);
  window.addEventListener("hashchange", () => route(true));
  route(true);
  setInterval(poll, 1000);
}

window.selectSub = function selectSub(id) {
  S.sid = id; localStorage.setItem("gi_sid", id); $("#subSel").value = id; route(true);
};
const selectSub = window.selectSub;

async function control(act, body) {
  if (act === "stop" && !(await confirmDialog("Stop replay?", "The replay will rewind to the first record. Alerts raised so far are kept until the next start.", "Stop"))) return;
  try { applyStatus(await api(`/replay/${act}`, { method: "POST", body })); route(false, true); } catch (e) { toast({ title: "REPLAY", text: e.message, color: color("HIGH RISK") }); }
}

function applyStatus(st) {
  S.status = st;
  $("#clock").textContent = ts(st.timestamp);
  const r = $("#rstate"); r.textContent = st.mode; r.className = "state mono " + st.mode;
  $("#prog").style.width = `${((st.cursor + 1) / st.total) * 100}%`;
  document.querySelectorAll("#speed [data-s]").forEach((b) => b.classList.toggle("on", +b.dataset.s === st.speed));
}

async function poll() {
  if (document.hidden || !S.token) return;
  try {
    const st = await api("/replay/status");
    applyStatus(st);
    for (const ev of st.recent_events) {
      if (ev.type === "ALERT" && ev.alert_id > S.lastAlert) {
        S.lastAlert = ev.alert_id;
        toast({ title: `${ev.risk_category} · RISK ${Math.round(ev.risk_score)} · CONF ${Math.round(ev.confidence)}%`, color: color(ev.risk_category),
          text: ev.message, sub: `${ev.parameter_label || ""} · ${ts(ev.timestamp)} · click to investigate`,
          onClick: () => (location.hash = `#/investigate/${ev.substation_id}/${ev.timestamp}`) });
      }
    }
    const n = st.recent_events.filter((e) => e.type === "ALERT").length;
    const c = $("#alertCount"); c.hidden = !n; c.textContent = n;
    const key = `${st.cursor}|${st.mode}`;
    if (key !== lastKey) { lastKey = key; route(false); }
  } catch { /* transient */ }
}

// ------------------------------------------------------------------------------------- router
function current() { const p = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean); return [ROUTES[p[0]] ? p[0] : "command", ...p.slice(1)]; }

async function route(full, force) {
  const [name, ...args] = current();
  if (!full && !force && !LIVE.has(name)) return;
  if (busy && !full) return;
  busy = true;
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("on", a.dataset.r === name));
  const sname = S.subs.find((s) => s.id === S.sid)?.name || "";
  $("#crumbs").innerHTML = `GridIntel / <b>${ROUTES[name][0]}</b>${["command", "fleet", "models"].includes(name) ? "" : ` / <span class="mono">${esc(name === "investigate" && args[0] ? (S.subs.find((s) => s.id === args[0])?.name || args[0]) : sname)}</span>`}`;
  document.title = `${window.GI18N ? window.GI18N.phrase(ROUTES[name][0]) : ROUTES[name][0]} · GridIntel`;
  try {
    if (full) { destroyCharts(); window.scrollTo({ top: 0 }); }
    await ROUTES[name][1](...args);
  } catch (e) { $("#view").innerHTML = errorState(e); }
  finally { busy = false; $("#rail").classList.remove("open"); }
}

// ------------------------------------------------------------------------------------- palette & shortcuts
function paletteItems() {
  const items = Object.entries(ROUTES).map(([k, [l]], i) => ({ label: l, hint: `page · ${i + 1}`, run: () => (location.hash = "#/" + k) }));
  S.subs.forEach((s) => items.push({ label: s.name, hint: s.has_model ? "substation" : "no source readings", run: () => selectSub(s.id) }));
  items.push({ label: "Demo: 02 Feb 10:00 — 11 kV T-I voltage 0 kV", hint: "investigation", run: () => (location.hash = "#/investigate/220-sec-46/2026-02-02T10:00:00") });
  items.push({ label: "Demo: 10 Feb 08:00 — T-2 incomer & feeders 0 A", hint: "investigation", run: () => (location.hash = "#/investigate/220-sec-46/2026-02-10T08:00:00") });
  ["start", "pause", "next", "stop"].forEach((a) => items.push({ label: `Replay: ${a}`, hint: "action", run: () => control(a) }));
  items.push({ label: "Sign out", hint: "action", run: () => logout() });
  return items;
}
function openPalette() {
  const p = $("#palette"), inp = $("#paletteInput"), list = $("#paletteList"), all = paletteItems();
  let sel = 0, shown = all;
  const render = () => { list.innerHTML = shown.map((x, i) => `<li class="${i === sel ? "sel" : ""}" data-i="${i}">${esc(x.label)}<small>${esc(x.hint)}</small></li>`).join(""); };
  const close = () => { p.hidden = true; };
  inp.value = ""; render(); p.hidden = false; inp.focus();
  inp.oninput = () => { const q = inp.value.toLowerCase(); shown = all.filter((x) => (x.label + " " + x.hint).toLowerCase().includes(q)); sel = 0; render(); };
  inp.onkeydown = (e) => {
    if (e.key === "ArrowDown") { sel = Math.min(sel + 1, shown.length - 1); render(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { sel = Math.max(sel - 1, 0); render(); e.preventDefault(); }
    else if (e.key === "Enter" && shown[sel]) { close(); shown[sel].run(); }
    else if (e.key === "Escape") close();
  };
  list.onclick = (e) => { const li = e.target.closest("li"); if (li) { close(); shown[+li.dataset.i].run(); } };
  p.onclick = (e) => e.target === p && close();
}
$("#paletteBtn").onclick = openPalette;
$("#menuBtn").onclick = () => $("#rail").classList.toggle("open");
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); return; }
  if (e.target.matches("input, textarea, select") || !S.token || $("#shell").hidden) return;
  if (e.key === "Escape") { document.getElementById("drawer").classList.remove("open"); return; }
  const keys = Object.keys(ROUTES);
  if (/^[1-8]$/.test(e.key)) location.hash = "#/" + keys[+e.key - 1];
  else if (e.key === " ") { e.preventDefault(); control(S.status?.mode === "RUNNING" ? "pause" : "start"); }
  else if (e.key.toLowerCase() === "n") control("next");
  else if (e.key === "/") { e.preventDefault(); openPalette(); }
});

// language change: re-render the current page so API sentences are rebuilt from their templates
window.addEventListener("gi:lang", () => { document.getElementById("drawer").classList.remove("open"); if (S.token && !$("#shell").hidden) route(true); });

// ------------------------------------------------------------------------------------- go
if (S.token && S.user) start(); else $("#login").hidden = false;
