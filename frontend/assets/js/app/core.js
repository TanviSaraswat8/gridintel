// GridIntel web — core: config, API client (JWT), formatting, UI primitives, charts.
export const API = ((window.GRIDINTEL_CONFIG && window.GRIDINTEL_CONFIG.API_URL) || "").replace(/\/$/, "") + "/api/v1";
export const COLORS = { NORMAL: "#3cc483", WATCH: "#e9c04a", WARNING: "#f09a3e", "HIGH RISK": "#f0544f", CRITICAL: "#ff2d6f" };
export const SERIES = ["#38c8e8", "#8fd3a6", "#c7a3f0", "#f0c06a", "#6fb4ff", "#f08f8f", "#9fb0c3", "#7fe0d0"];
export const S = { token: sessionStorage.getItem("gi_token"), user: JSON.parse(sessionStorage.getItem("gi_user") || "null"),
  sid: localStorage.getItem("gi_sid") || "220-sec-46", subs: [], status: null, lastAlert: 0, listeners: new Set() };

export class ApiError extends Error { constructor(status, msg) { super(msg); this.status = status; } }

export async function api(path, opts = {}) {
  // api(path, {params|method|body|raw}) or shorthand api(path, {queryParam: value, ...})
  const isOpts = ["method", "body", "params", "raw"].some((k) => k in opts);
  const { method = "GET", body, params, raw } = isOpts ? opts : { params: opts };
  const q = params ? "?" + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")) : "";
  const r = await fetch(API + path + q, { method, headers: { ...(S.token ? { Authorization: "Bearer " + S.token } : {}), ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined });
  if (r.status === 401) { logout(true); throw new ApiError(401, "Session expired"); }
  if (!r.ok) { let m = r.statusText; try { const j = await r.json(); m = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch {} throw new ApiError(r.status, m); }
  return raw ? r : r.json();
}

export function logout(expired) {
  sessionStorage.removeItem("gi_token"); sessionStorage.removeItem("gi_user"); S.token = null;
  if (expired) toast({ title: "SESSION", text: "Please sign in again.", color: COLORS.WATCH });
  document.getElementById("shell").hidden = true; document.getElementById("login").hidden = false;
}

// ---------------------------------------------------------------------------- formatting
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(+v) ? "—" : (+(+v).toFixed(d)).toLocaleString(undefined, { maximumFractionDigits: d }));
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
// log sheets record the last reading as 24:00 — stored as next-day 00:00, displayed as 24:00 of the log day
function shift(t) {
  if (!t || t.slice(11, 16) !== "00:00") return [t, t ? t.slice(11, 16) : ""];
  const d = new Date(t.slice(0, 10) + "T12:00:00Z"); d.setUTCDate(d.getUTCDate() - 1);
  return [d.toISOString().slice(0, 10), "24:00"];
}
export const ts = (t) => { if (!t) return "—"; const [d, h] = shift(t); return `${d.slice(8, 10)} ${MON[+d.slice(5, 7) - 1]} ${d.slice(0, 4)} · ${h}`; };
export const tsShort = (t) => { if (!t) return ""; const [d, h] = shift(t); return `${d.slice(8, 10)}/${d.slice(5, 7)} ${h}`; };
export const cls = (c) => "c-" + String(c || "NA").replace(/\s+/g, "");
export const badge = (c) => `<span class="badge ${cls(c)}">${esc(c || "NO DATA")}</span>`;
export const color = (c) => COLORS[c] || "#4b5869";

// ---------------------------------------------------------------------------- UI primitives
export function toast({ title, text, sub, color: col = COLORS.WARNING, onClick, ttl = 9000 }) {
  const t = document.createElement("div");
  t.className = "toast glass"; t.style.color = col;
  t.innerHTML = `<div class="t1">${esc(title)}</div><div class="t2">${esc(text)}</div>${sub ? `<div class="t3">${esc(sub)}</div>` : ""}`;
  t.onclick = () => { onClick && onClick(); t.remove(); };
  document.getElementById("toasts").prepend(t);
  setTimeout(() => t.remove(), ttl);
}

export function confirmDialog(title, text, okLabel = "Confirm") {
  return new Promise((res) => {
    const m = document.getElementById("modal"), b = document.getElementById("modalBox");
    b.innerHTML = `<h3 style="margin:0 0 8px">${esc(title)}</h3><p class="dim" style="margin:0 0 18px">${esc(text)}</p>
      <div class="row" style="justify-content:flex-end"><button class="btn" data-x="0">Cancel</button><button class="btn btn-primary" data-x="1">${esc(okLabel)}</button></div>`;
    m.hidden = false;
    const done = (v) => { m.hidden = true; res(v); };
    b.querySelectorAll("button").forEach((x) => (x.onclick = () => done(x.dataset.x === "1")));
    m.onclick = (e) => e.target === m && done(false);
    b.querySelector(".btn-primary").focus();
  });
}

export function drawer(html) {
  const d = document.getElementById("drawer"); document.getElementById("drawerBody").innerHTML = html;
  d.classList.add("open"); d.setAttribute("aria-hidden", "false");
  d.onclick = (e) => { if (e.target === d || e.target.closest("[data-close]")) closeDrawer(); };
}
export function closeDrawer() { const d = document.getElementById("drawer"); d.classList.remove("open"); d.setAttribute("aria-hidden", "true"); }

export const skeleton = (rows = 3, h = 120) => `<div class="grid">${Array.from({ length: rows }, () => `<div class="sk" style="height:${h}px"></div>`).join("")}</div>`;
export const emptyState = (t) => `<div class="empty">${esc(t)}</div>`;
export const errorState = (e) => `<div class="panel error">${esc(e.message || e)}</div>`;

export function gauge(value, cat) {
  const v = Math.max(0, Math.min(100, value || 0)), a = Math.PI * (1 - v / 100);
  const x = 110 + 90 * Math.cos(a), y = 110 - 90 * Math.sin(a), col = color(cat);
  return `<div class="gauge"><svg viewBox="0 0 220 130"><path d="M20 110 A90 90 0 0 1 200 110" stroke="rgba(255,255,255,.07)" stroke-width="12" fill="none" stroke-linecap="round"/>
    <path d="M20 110 A90 90 0 0 1 ${x.toFixed(1)} ${y.toFixed(1)}" stroke="${col}" stroke-width="12" fill="none" stroke-linecap="round" style="filter:drop-shadow(0 0 6px ${col})"/></svg>
    <div class="val"><div><b style="color:${col}">${fmt(value, 0)}</b><span>RISK / 100</span></div></div></div>`;
}

// ---------------------------------------------------------------------------- charts
const CH = {};
export function destroyCharts() { for (const k in CH) { CH[k].destroy(); delete CH[k]; } }
if (window.Chart) {
  Object.assign(Chart.defaults, { color: "#93a1b2", borderColor: "rgba(130,170,210,.08)", animation: { duration: 250 } });
  Chart.defaults.font.family = "Inter, Segoe UI, system-ui, sans-serif"; Chart.defaults.font.size = 11;
  Chart.defaults.plugins.legend.labels.boxWidth = 10; Chart.defaults.plugins.legend.labels.boxHeight = 2;
  Chart.defaults.plugins.tooltip.backgroundColor = "#0b1016"; Chart.defaults.plugins.tooltip.borderColor = "rgba(130,170,210,.25)"; Chart.defaults.plugins.tooltip.borderWidth = 1;
}
const focusLine = { id: "focusLine", afterDatasetsDraw(c, _a, o) { if (o.index == null) return; const x = c.scales.x.getPixelForValue(o.index); const { top, bottom } = c.chartArea;
  const g = c.ctx; g.save(); g.strokeStyle = "rgba(56,200,232,.7)"; g.setLineDash([4, 4]); g.beginPath(); g.moveTo(x, top); g.lineTo(x, bottom); g.stroke(); g.restore(); } };

export function line(id, labels, sets, o = {}) {
  const el = document.getElementById(id); if (!el) return;
  CH[id] && CH[id].destroy();
  CH[id] = new Chart(el, { type: "line", plugins: [focusLine],
    data: { labels, datasets: sets.map((d, i) => ({ borderColor: d.color || SERIES[i % SERIES.length], backgroundColor: d.fill || "transparent", borderWidth: d.w || 1.7,
      pointRadius: d.points ?? (labels.length < 30 ? 2 : 0), pointHoverRadius: 4, tension: .25, spanGaps: true, fill: !!d.fill, borderDash: d.dash || [], yAxisID: d.axis || "y", ...d })) },
    options: { maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: sets.length > 1, position: "bottom" }, focusLine: { index: o.focus } },
      scales: { x: { ticks: { maxRotation: 0, autoSkipPadding: 16 }, grid: { color: "rgba(130,170,210,.05)" } },
        y: { grid: { color: "rgba(130,170,210,.06)" }, title: { display: !!o.y, text: o.y }, min: o.min, max: o.max },
        ...(o.y2 ? { y2: { position: "right", min: 0, max: 100, grid: { display: false }, title: { display: true, text: o.y2 } } } : {}) } } });
  return CH[id];
}
export function bars(id, labels, data, colors, o = {}) {
  const el = document.getElementById(id); if (!el) return;
  CH[id] && CH[id].destroy();
  CH[id] = new Chart(el, { type: "bar", data: { labels, datasets: [{ data, backgroundColor: colors || "#38c8e8", borderRadius: 3, barPercentage: .85, categoryPercentage: .9 }] },
    options: { maintainAspectRatio: false, indexAxis: o.h ? "y" : "x", plugins: { legend: { display: false } },
      scales: { x: { grid: { color: "rgba(130,170,210,.05)" }, title: { display: !!o.x, text: o.x } }, y: { grid: { color: "rgba(130,170,210,.06)" }, ticks: { autoSkip: false } } } } });
}
export const riskSet = (vals, label = "AI risk") => ({ label, data: vals, axis: "y2", color: "#e4eaf1", w: 1.4,
  segment: { borderColor: (c) => riskColorVal(c.p1.parsed.y) }, pointBackgroundColor: vals.map(riskColorVal), pointRadius: vals.map((v) => (v > 55 ? 3.5 : 1.2)) });
export const riskColorVal = (v) => (v > 90 ? COLORS.CRITICAL : v > 75 ? COLORS["HIGH RISK"] : v > 55 ? COLORS.WARNING : v > 30 ? COLORS.WATCH : COLORS.NORMAL);

export function download(name, blob) { const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000); }
