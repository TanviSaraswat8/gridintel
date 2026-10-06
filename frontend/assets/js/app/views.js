// GridIntel web — page views.
import { S, api, badge, bars, closeDrawer, cls, color, download, drawer, emptyState, esc, fmt, gauge, line, riskColorVal, riskSet,
  SERIES, skeleton, toast, ts, tsShort } from "./core.js";

const $v = () => document.getElementById("view");
const sub = (id) => S.subs.find((x) => x.id === id) || {};
const goInv = (sid, t) => (location.hash = `#/investigate/${sid}/${t}`);
// render an API sentence in the viewer's language from its [template key, args] pair (falls back to English)
const say = (en, pair) => (window.GI18N ? window.GI18N.tr(en || "", pair) : en || "");
const sayRule = (r, f) => say(r[f === "msg" ? "message" : "investigate"], r.i18n && r.i18n[f]);

// ======================================================================== COMMAND CENTER
export async function command() {
  $v().innerHTML = skeleton(3, 140);
  const [cc, demo] = await Promise.all([api("/command-center"), api("/investigations/demo")]);
  const prim = cc.substations.find((x) => x.substation_id === S.sid) || cc.substations[0];
  const hist = prim ? await api("/scada/history", { substation: prim.substation_id, upto_cursor: true, last: 48 }) : null;
  const hcol = cc.grid_health == null ? "#93a1b2" : riskColorVal(100 - cc.grid_health);
  $v().innerHTML = `
  <div class="page-head"><div><h1>Command Center</h1><div class="sub">Grid health, AI risk and alerts at replay time <b class="mono">${ts(cc.replay.timestamp)}</b> · ${esc(cc.model_version)}</div></div>
    <div class="row"><span class="badge c-WATCH">HISTORICAL REPLAY</span><span class="badge c-NA">LIVE INGESTION NOT CONNECTED</span></div></div>
  <div class="kpis">
    <div class="kpi accent" style="color:${hcol}"><div class="k">Grid health</div><div class="v">${cc.grid_health == null ? "—" : fmt(cc.grid_health, 1) + "%"}</div><div class="s" data-tip="${esc(cc.grid_health_note)}">100 − mean AI risk ⓘ</div></div>
    <div class="kpi"><div class="k">Active substations</div><div class="v">${cc.active_substations}<span class="faint" style="font-size:16px"> / ${cc.sheets_total}</span></div><div class="s">${cc.sheets_total - cc.substations_with_data} sheets: no source readings</div></div>
    <div class="kpi accent" style="color:${cc.active_alerts ? "#f09a3e" : "#93a1b2"}"><div class="k">Active alerts</div><div class="v">${cc.active_alerts}</div><div class="s">raised during this replay</div></div>
    <div class="kpi accent" style="color:${cc.high_risk_events ? "#f0544f" : "#93a1b2"}"><div class="k">High-risk events</div><div class="v">${cc.high_risk_events}</div><div class="s">HIGH RISK + CRITICAL</div></div>
    <div class="kpi"><div class="k">Model status</div><div class="v online" style="font-size:22px">${esc(cc.model_status)}</div><div class="s">Ensemble · LODO-validated</div></div>
  </div>
  <div class="sp"></div>
  <div class="grid g-main">
    <div class="panel"><h3>Substation network <span class="hint">node colour = AI risk at replay time · click a node to investigate</span></h3>${network(cc)}</div>
    <div class="grid">
      <div class="panel"><h3>Demo investigations <span class="hint">real events in the supplied files</span></h3>
        <div class="grid">${demo.items.map((d) => `<div class="demo-card" data-inv="${d.substation_id}|${d.timestamp}">
          <div class="row">${badge(d.risk_category)}<span class="mono tiny dim">${ts(d.timestamp)}</span><span class="right mono tiny">${fmt(d.risk_score, 0)}/100</span></div>
          <div class="t">${esc(d.title)}</div><div class="tiny dim">220 kV Sector-46 · confidence ${fmt(d.confidence, 0)}%</div></div>`).join("")}</div></div>
      <div class="panel"><h3>Recent alerts <span class="hint">${cc.active_alerts} total</span></h3>${alertList(cc.recent_alerts.slice(0, 5), "No alerts yet — press ▶ to replay the historical records.")}</div>
    </div>
  </div>
  <div class="sp"></div>
  <div class="grid g-main">
    <div class="panel"><h3>${esc(prim ? prim.name : "")} · AI risk and anomaly score <span class="hint">last 48 replayed hours</span></h3><div class="chart"><canvas id="ccR"></canvas></div></div>
    <div class="panel"><h3>Risk distribution now</h3>${riskBars(cc.category_counts)}<div class="sp"></div><div class="note">${esc(cc.risk_note)}</div></div>
  </div>`;
  bind();
  if (hist) line("ccR", hist.timestamps.map(tsShort), [{ label: "Anomaly score (0–100)", data: hist.anomaly, color: "#38c8e8", fill: "rgba(56,200,232,.06)" }, riskSet(hist.risk)], { y2: "risk", min: 0, max: 100 });
}

function network(cc) {
  const subs = cc.substations; const W = 760, H = 330, n = subs.length;
  const nodes = subs.map((s, i) => ({ ...s, x: 70 + (i * (W - 140)) / Math.max(1, n - 1), y: s.voltage_class_kv >= 220 ? 120 : 220 }));
  let g = `<div class="topo-scroll"><svg class="topo" viewBox="0 0 ${W} ${H}" role="img" aria-label="Substation network">`;
  g += `<line x1="30" y1="40" x2="${W - 30}" y2="40" class="wire bus" stroke="#5fa8ff" opacity=".55"/><text x="30" y="30" class="sub">220 kV TRANSMISSION · HVPNL FARIDABAD (schematic placement)</text>`;
  nodes.forEach((s) => {
    const col = s.available ? color(s.risk_category) : "#4b5869";
    g += `<path d="M${s.x} 40 V${s.y - 22}" class="wire"/><path d="M${s.x} 40 V${s.y - 22}" class="flow"/>`;
    g += `<g class="node" data-node="${s.substation_id}" style="color:${col}">`;
    if (s.available && ["HIGH RISK", "CRITICAL", "WARNING"].includes(s.risk_category)) g += `<circle cx="${s.x}" cy="${s.y}" r="22" fill="none" stroke="${col}" class="pulse-ring"/>`;
    g += `<circle cx="${s.x}" cy="${s.y}" r="22" fill="rgba(12,17,23,.95)" stroke="${col}" stroke-width="2.2"/>
      <text x="${s.x}" y="${s.y + 4}" text-anchor="middle" class="lbl" style="fill:${col}">${s.available ? fmt(s.risk_score, 0) : "—"}</text>
      <text x="${s.x}" y="${s.y + 42}" text-anchor="middle" class="lbl">${esc(s.name)}</text>
      <text x="${s.x}" y="${s.y + 56}" text-anchor="middle" class="sub">${s.available ? esc(s.risk_category) : "no record at this time"}</text>`;
    (s.transformers || []).slice(0, 4).forEach((t, j, arr) => {
      const tx = s.x + (j - (arr.length - 1) / 2) * 26, ty = s.y + 86;
      g += `<path d="M${s.x} ${s.y + 62} L${tx} ${ty - 8}" class="wire"/><circle cx="${tx}" cy="${ty}" r="7" fill="none" stroke="rgba(120,170,220,.5)"/><text x="${tx}" y="${ty + 20}" text-anchor="middle" class="sub">${esc(t)}</text>`;
    });
    g += `</g>`;
  });
  return g + `</svg></div>`;
}

function riskBars(counts) {
  const cats = ["NORMAL", "WATCH", "WARNING", "HIGH RISK", "CRITICAL"], tot = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
  return cats.map((c) => `<div class="row" style="margin:6px 0"><span style="width:84px" class="mono tiny ${cls(c)}">${c}</span>
    <div class="bar" style="flex:1"><i style="width:${((counts[c] || 0) / tot) * 100}%;background:${color(c)}"></i></div><span class="mono tiny" style="width:20px;text-align:right">${counts[c] || 0}</span></div>`).join("");
}

export function alertList(items, empty) {
  if (!items.length) return emptyState(empty);
  return `<div>${items.map((a) => `<div class="tl-item" style="color:${color(a.risk_category)}" data-inv="${a.substation_id}|${a.record_timestamp}">
    <span class="dot"></span><div style="min-width:0;color:var(--text)"><div class="row"><span class="t">${esc(a.substation_name)}</span><span class="right">${badge(a.risk_category)}</span></div>
    <div class="d">${esc(a.parameter_label || "Potential abnormal operating condition")}${a.equipment ? " · " + esc(a.equipment) : ""}</div>
    <div class="tiny faint mono">${ts(a.record_timestamp)} · risk ${fmt(a.risk_score, 0)} · conf ${fmt(a.confidence, 0)}%</div></div></div>`).join("")}</div>`;
}

function bind() {
  document.querySelectorAll("[data-inv]").forEach((e) => (e.onclick = () => { const [s, t] = e.dataset.inv.split("|"); goInv(s, t); }));
  document.querySelectorAll("[data-node]").forEach((e) => (e.onclick = async () => {
    const id = e.dataset.node;
    const h = await api("/anomalies", { substation: id, min_risk: 56, size: 1, end: S.status?.timestamp });
    if (h.items.length) goInv(id, h.items[0].record_timestamp);
    else { S.sid = id; localStorage.setItem("gi_sid", id); location.hash = "#/digital"; }
  }));
}

// ======================================================================== SCADA LIVE
let scadaMode = "replay";
export async function scada() {
  const sid = S.sid;
  if (!sub(sid).has_model) { $v().innerHTML = noData(sid); return; }
  const [lat, h] = await Promise.all([api("/scada/latest", { substation: sid }), api("/scada/history", { substation: sid, upto_cursor: true, last: 24 })]);
  const r = lat.record;
  const demo = scadaMode === "demo" ? (await api("/investigations/demo")).items : [];
  $v().innerHTML = `
  <div class="page-head"><div><h1>SCADA Live · ${esc(sub(sid).name)}</h1><div class="sub">${r && r.available ? `Record ${ts(r.timestamp)} · values from the HVPNL log sheet` : "No record at the current replay time"}</div></div>
    <div class="tabs"><button disabled data-tip="Live ingestion not connected — no live SCADA feed is configured">LIVE</button>
      <button data-m="replay" class="${scadaMode === "replay" ? "on" : ""}">HISTORICAL REPLAY</button><button data-m="demo" class="${scadaMode === "demo" ? "on" : ""}">DEMO</button></div></div>
  ${scadaMode === "demo" ? `<div class="panel"><h3>Demo — jump the replay to a real recorded event</h3><div class="grid g2">${demo.map((d) => `<div class="demo-card" data-seek="${d.timestamp}">
     <div class="row">${badge(d.risk_category)}<span class="mono tiny dim">${ts(d.timestamp)}</span></div><div class="t">${esc(d.title)}</div><div class="tiny dim">${esc(d.summary)}</div></div>`).join("")}</div></div><div class="sp"></div>` : ""}
  <div class="panel" style="border-color:rgba(130,170,210,.06)"><div class="row wrap">
    <span class="mono tiny faint">LIVE INGESTION</span><span class="badge c-NA">NOT CONNECTED</span><span class="mono tiny faint" style="margin-left:14px">SOURCE</span><span class="tiny">HVPNL Faridabad daily log — hourly, replayed</span>
    ${r && r.available ? `<span class="right row">${badge(r.risk_category)}<span class="mono">risk ${fmt(r.risk_score, 0)} · conf ${fmt(r.confidence, 0)}%</span></span>` : ""}</div></div>
  <div class="sp"></div>
  ${r && r.available ? `<div class="metrics">${metricCards(r.cards)}</div>` : ""}
  <div class="sp"></div>
  <div class="grid g2">
    <div class="panel"><h3>Voltage <span class="hint">kV</span></h3><div class="chart"><canvas id="sV"></canvas></div></div>
    <div class="panel"><h3>Load <span class="hint">transformer loading</span></h3><div class="chart"><canvas id="sL"></canvas></div></div>
    <div class="panel"><h3>Current <span class="hint">Σ logged feeder currents, A</span></h3><div class="chart"><canvas id="sC"></canvas></div></div>
    <div class="panel"><h3>Temperature <span class="hint">winding / oil, °C</span></h3><div class="chart"><canvas id="sT"></canvas></div></div>
  </div>
  <div class="sp"></div>
  <div class="panel"><h3>Breaker / circuit state <span class="hint">as logged by operators this hour</span></h3>
    ${r && r.available ? `<div>${r.states.filter((x) => x.state !== "CLEAR").map((x) => `<span class="chip ${x.state}" data-tip="${esc(x.parameter)}">${esc(x.name)} · ${x.state}</span>`).join("") || emptyState("No states logged")}</div>` : ""}</div>`;
  document.querySelectorAll("[data-m]").forEach((b) => (b.onclick = () => { scadaMode = b.dataset.m; scada(); }));
  document.querySelectorAll("[data-seek]").forEach((b) => (b.onclick = async () => { await api("/replay/seek", { method: "POST", body: { timestamp: b.dataset.seek } }); toast({ title: "REPLAY", text: "Jumped to " + ts(b.dataset.seek), color: "#38c8e8", ttl: 3000 }); }));
  const L = h.timestamps.map(tsShort), sg = h.signals;
  line("sV", L, sg.voltages.slice(0, 4).map((s) => ({ label: s.name, data: s.values })));
  line("sL", L, sg.transformer_loads.slice(0, 4).map((s) => ({ label: `${s.name} (${s.unit})`, data: s.values })));
  line("sC", L, sg.feeder_total.map((s) => ({ label: s.name, data: s.values, fill: "rgba(56,200,232,.07)" })));
  const temps = sg.transformer_temperature.length ? sg.transformer_temperature : sg.oil_temperature;
  if (temps.length) line("sT", L, temps.slice(0, 6).map((s) => ({ label: s.name, data: s.values })));
  else document.getElementById("sT").parentElement.innerHTML = emptyState("Temperatures are not logged at this substation.");
}

export function metricCards(c) {
  const m = (x, d = 1) => `<div class="metric"><div class="k">${esc(x.label)}</div><div class="v">${fmt(x.value, d)}<small>${esc(x.unit || "")}</small></div><div class="n" title="${esc(x.parameter || "")}">${esc(x.name)}</div></div>`;
  const b = c.breaker_state, ab = Object.keys(b.abnormal || {});
  return m(c.voltage) + m(c.current) + m(c.transformer_load, 2) + m(c.transformer_temperature, 0) + m(c.feeder_load, 0) +
    `<div class="metric" style="${ab.length ? "border-color:rgba(233,192,74,.5)" : ""}"><div class="k">${esc(b.label)}</div>
     <div style="margin-top:6px">${Object.entries(b.counts).map(([k, v]) => `<span class="chip ${k}">${k} ${v}</span>`).join("") || '<span class="faint tiny">none logged</span>'}</div>
     <div class="n">${ab.length ? ab.length + " PTW / breakdown" : "no PTW / breakdown"}</div></div>`;
}

const noData = (sid) => `<div class="panel"><h3>${esc(sub(sid).name || sid)}</h3><div class="empty"><span class="badge c-NA">NO DATA AVAILABLE</span><p>Data unavailable in supplied records — this sheet is a blank template in all three files.</p></div></div>`;

// ======================================================================== DIGITAL SUBSTATION
export async function digital() {
  const sid = S.sid;
  if (!sub(sid).has_model) { $v().innerHTML = noData(sid); return; }
  const t = await api(`/substations/${sid}/topology`);
  if (!t.available) { $v().innerHTML = emptyState("No record at the current replay time."); return; }
  $v().innerHTML = `
  <div class="page-head"><div><h1>Digital Substation · ${esc(t.substation.name)}</h1><div class="sub">${ts(t.timestamp)} · ${badge(t.risk_category)} risk ${fmt(t.risk_score, 0)} · click equipment for details</div></div>
    <div class="row tiny dim"><span class="badge c-NORMAL">healthy</span><span class="badge c-WATCH">watch</span><span class="badge c-WARNING">warning</span><span class="badge c-HIGHRISK">risk</span></div></div>
  <div class="panel">${sld(t)}</div><div class="sp"></div><div class="note">${esc(t.note)}</div>`;
  const all = [...t.buses, ...t.transformers, ...t.feeders, ...t.couplers];
  document.querySelectorAll("[data-eq]").forEach((e) => (e.onclick = () => equipDrawer(all[+e.dataset.eq], t)));
}

function sld(t) {
  const W = 1100, all = [...t.buses, ...t.transformers, ...t.feeders, ...t.couplers], idx = (n) => all.indexOf(n);
  const lv = [...new Set(t.buses.map((b) => b.voltage_kv))].sort((a, b) => b - a);
  const has11 = t.feeders.some((f) => f.voltage_kv === 11) && !lv.includes(11);
  const levels = has11 ? [...lv, 11] : lv; if (!levels.length) levels.push(t.substation.voltage_class_kv, 11);
  const Y = Object.fromEntries(levels.map((k, i) => [k, 70 + i * 210]));
  const H = 70 + (levels.length - 1) * 210 + 150;
  let g = `<div class="topo-scroll"><svg class="topo" viewBox="0 0 ${W} ${H}" role="img" aria-label="Single-line diagram">`;
  const st = (n) => color(n.status === "NORMAL" ? "NORMAL" : n.status);
  levels.forEach((k) => {
    const bus = t.buses.find((b) => b.voltage_kv === k);
    const col = bus ? st(bus) : "rgba(120,170,220,.4)";
    g += `<g ${bus ? `class="node" data-eq="${idx(bus)}"` : ""} style="color:${col}"><line x1="40" y1="${Y[k]}" x2="${W - 40}" y2="${Y[k]}" class="wire bus" stroke="${col}"/>
      <text x="40" y="${Y[k] - 10}" class="lbl" style="fill:${col}">${k} kV ${bus ? "BUS" : "SECTION (feeders)"}</text>${bus ? `<text x="${W - 40}" y="${Y[k] - 10}" text-anchor="end" class="sub">${bus.values.map((v) => `${esc(v.name)} ${fmt(v.value, 1)} kV`).join(" · ")}</text>` : ""}</g>`;
  });
  // transformers between their HV and LV levels
  const tiers = {};
  t.transformers.forEach((x) => { const k = levels.includes(x.hv_kv) ? x.hv_kv : levels[0]; (tiers[k] = tiers[k] || []).push(x); });
  Object.entries(tiers).forEach(([k, arr]) => {
    const y0 = Y[k], lvk = levels[levels.indexOf(+k) + 1], y1 = lvk ? Y[lvk] : y0 + 160;
    arr.forEach((x, i) => {
      const cx = 140 + i * 150, my = (y0 + y1) / 2, col = st(x);
      const load = x.values.find((v) => v.unit === "MVA") || x.values.find((v) => v.unit === "A");
      const temp = x.values.filter((v) => v.unit === "°C" && v.value != null).sort((a, b) => b.value - a.value)[0];
      g += `<path d="M${cx} ${y0} V${my - 26}" class="wire"/><path d="M${cx} ${y0} V${my - 26}" class="flow"/><path d="M${cx} ${my + 26} V${y1}" class="wire"/>
        <g class="node" data-eq="${idx(x)}" style="color:${col}">${x.status !== "NORMAL" ? `<circle cx="${cx}" cy="${my}" r="24" fill="none" stroke="${col}" class="pulse-ring"/>` : ""}
        <circle cx="${cx}" cy="${my - 9}" r="17" fill="rgba(12,17,23,.96)" stroke="${col}" stroke-width="2"/><circle cx="${cx}" cy="${my + 9}" r="17" fill="none" stroke="${col}" stroke-width="2"/>
        <text x="${cx + 26}" y="${my - 8}" class="lbl" style="fill:${col}">${esc(x.tag)}</text>
        <text x="${cx + 26}" y="${my + 6}" class="sub">${x.rating_mva ? x.rating_mva + " MVA · " : ""}${x.hv_kv}/${x.lv_kv} kV</text>
        <text x="${cx + 26}" y="${my + 19}" class="sub">${load ? fmt(load.value, 1) + " " + load.unit : ""}${temp ? " · " + fmt(temp.value, 0) + "°C" : ""}</text></g>`;
    });
  });
  // feeders as drops below their level; couplers on the bus
  levels.forEach((k) => {
    const fs = t.feeders.filter((f) => f.voltage_kv === k), y = Y[k];
    const start = k === levels[levels.length - 1] ? 80 : 40 + 150 * ((tiers[k] || []).length) + 120;
    const step = Math.max(26, Math.min(60, (W - 60 - start) / Math.max(1, fs.length)));
    fs.forEach((f, i) => {
      const x = start + i * step, col = st(f), v = f.values[0];
      g += `<g class="node" data-eq="${idx(f)}" style="color:${col}"><path d="M${x} ${y} V${y + 44}" class="wire" stroke="${col}"/><rect x="${x - 5}" y="${y + 44}" width="10" height="10" rx="2" fill="${v && v.value === 0 ? "transparent" : col}" stroke="${col}"/>
        <text x="${x}" y="${y + 66}" transform="rotate(50 ${x} ${y + 66})" class="sub">${esc(f.tag.replace(/^\d+\s*kv\s*/i, "").replace(/^sector\s*\d+\s*-\s*/i, "").slice(0, 16))}</text></g>`;
    });
    t.couplers.filter((c) => c.voltage_kv === k).forEach((c) => {
      g += `<g class="node" data-eq="${idx(c)}" style="color:${st(c)}"><rect x="${W - 110}" y="${y - 8}" width="16" height="16" fill="rgba(12,17,23,.96)" stroke="${st(c)}"/><text x="${W - 88}" y="${y + 22}" class="sub">coupler</text></g>`;
    });
  });
  return g + "</svg></div>";
}

function equipDrawer(n, t) {
  drawer(`<div class="row"><h2 style="margin:0">${esc(n.tag)}</h2><span class="right">${badge(n.status)}</span><button class="btn btn-ghost btn-sm" data-close>✕</button></div>
    <div class="tiny dim" style="margin:4px 0 14px">${esc(n.kind.toUpperCase())} · ${esc(t.substation.name)} · ${ts(t.timestamp)}</div>
    <div class="panel"><h3>Current state</h3><table><tbody>${n.values.map((v) => `<tr><td>${esc(v.name)}</td><td class="n">${v.value == null ? (v.state || "—") : fmt(v.value, 2) + " " + esc(v.unit)}</td></tr>`).join("")}</tbody></table></div>
    <div class="sp"></div>
    <div class="panel"><h3>Anomaly signals</h3>${n.signals.length || n.rules.length ? [...n.rules.map((r) => `<div class="sig"><div class="top"><b>${esc(r.title)}</b><span class="lvl lvl-High">RULE ${esc(r.rule)}</span></div><div class="o">${esc(sayRule(r, "msg"))}</div></div>`),
      ...n.signals.map((x) => `<div class="sig"><div class="top"><b>${esc(x.label)}</b><span class="lvl lvl-${x.level}">${x.level.toUpperCase()}</span></div><div class="o">${fmt(x.value, 2)} ${esc(x.unit || "")} · typical ${fmt(x.baseline_p10, 1)}–${fmt(x.baseline_p90, 1)}</div></div>`)].join("") : emptyState("No contributing signals on this equipment.")}</div>
    <div class="sp"></div>
    <div class="panel"><h3>Recent history</h3><div class="chart short"><canvas id="dH"></canvas></div></div>
    <div class="sp"></div><button class="btn btn-primary" id="dInv">Open investigation for this record →</button>`);
  document.getElementById("dInv").onclick = () => { closeDrawer(); goInv(t.substation.id, t.timestamp); };
  const params = n.values.filter((v) => v.value != null).slice(0, 3).map((v) => v.parameter);
  if (params.length) api("/scada/history", { substation: t.substation.id, end: t.timestamp, last: 24, params }).then((h) =>
    line("dH", h.timestamps.map(tsShort), h.signals.selected.map((s) => ({ label: `${s.name} (${s.unit})`, data: s.values }))));
}

// ======================================================================== INVESTIGATION WORKSPACE
export async function investigate(sid, t) {
  const [al, hist] = await Promise.all([api("/alerts", { size: 100 }), api("/anomalies", { min_risk: 56, size: 60 })]);
  if (!sid || !t) {
    const first = al.items[0] || hist.items[0];
    if (!first) { $v().innerHTML = emptyState("No anomalies to investigate."); return; }
    history.replaceState(null, "", `#/investigate/${first.substation_id}/${first.record_timestamp}`);
    sid = first.substation_id; t = first.record_timestamp;
  }
  $v().innerHTML = `<div class="ws"><div class="panel">${skeleton(5, 50)}</div><div class="panel">${skeleton(2, 200)}</div><div class="panel">${skeleton(4, 80)}</div></div>`;
  const d = await api("/investigations", { params: { substation: sid, timestamp: t } });
  const p = d.primary || {}, col = color(d.risk_category);
  const maxS = Math.max(...d.contributing_signals.map((x) => x.contribution_share), 0.01);
  const seen = new Set(); const items = [...al.items.map((a) => ({ ...a, src: "replay" })), ...hist.items.map((a) => ({ ...a, src: "history" }))].filter((a) => { const k = a.substation_id + a.record_timestamp; if (seen.has(k)) return false; seen.add(k); return true; });
  const canNote = ["ENGINEER", "ADMIN"].includes(S.user?.role);
  $v().innerHTML = `
  <div class="page-head"><div><h1>Investigation workspace</h1><div class="sub">${esc(d.substation.name)} · ${ts(d.timestamp)} · scored by <span class="mono">${esc(d.model_key)}</span> (${esc(d.evaluation)})</div></div>
    <div class="row"><button class="btn btn-sm" id="prevH">← previous hour</button><button class="btn btn-sm" id="nextH">next hour →</button></div></div>
  <div class="ws">
    <div class="panel"><h3>Alert timeline <span class="hint">${items.length} events</span></h3><div class="timeline">${items.map((a) => `<div class="tl-item ${a.substation_id === sid && a.record_timestamp === t ? "on" : ""}" style="color:${color(a.risk_category)}" data-inv="${a.substation_id}|${a.record_timestamp}">
      <span class="dot"></span><div style="min-width:0;color:var(--text)"><div class="t">${ts(a.record_timestamp)}</div><div class="d">${esc(a.substation_name)} · ${esc(a.parameter_label || "")}</div>
      <div class="tiny faint mono">${esc(a.risk_category)} · ${fmt(a.risk_score, 0)} · ${a.src === "replay" ? "replay alert" : "history"}</div></div></div>`).join("")}</div></div>
    <div class="grid">
      <div class="panel" style="border-top:2px solid ${col}"><div class="row wrap"><span class="mono tiny" style="color:${col};letter-spacing:.18em">${esc(d.title)}</span><span class="right">${badge(d.risk_category)}</span></div>
        <h2 style="margin:6px 0 4px;font-size:20px">${esc(d.affected_parameter || "Multiple signals")}</h2><div class="dim">${esc(say(d.message, d.i18n?.message))}</div>
        <div class="grid g4" style="margin-top:12px">
          <div class="metric"><div class="k">Current value</div><div class="v">${fmt(d.current_value, 2)}<small>${esc(p.unit || "")}</small></div></div>
          <div class="metric"><div class="k">Baseline median</div><div class="v">${fmt(p.baseline_median, 2)}<small>${esc(p.unit || "")}</small></div></div>
          <div class="metric"><div class="k">Anomaly score</div><div class="v">${fmt(d.anomaly_score, 0)}<small>/100</small></div></div>
          <div class="metric"><div class="k">How unusual</div><div class="v" style="font-size:18px">${esc(d.how_unusual).toUpperCase()}</div></div></div></div>
      <div class="panel"><h3>Signal trace <span class="hint">dashed vertical = this record · dashed lines = baseline medians</span></h3>
        <div class="row wrap" id="trSel" style="margin-bottom:8px">${d.trend.series.map((s, i) => `<label class="chip" style="cursor:pointer"><input type="checkbox" data-i="${i}" ${i < 3 ? "checked" : ""} style="margin:0 6px 0 0"/>${esc(s.name)}</label>`).join("")}</div>
        <div class="chart tall"><canvas id="iT"></canvas></div></div>
      <div class="panel"><h3>AI risk around the event</h3><div class="chart short"><canvas id="iR"></canvas></div></div>
      <div class="panel"><h3>Evidence <span class="hint">source measurements from the log sheet</span></h3><div class="tbl"><table><thead><tr><th>Parameter</th><th class="n">Value</th><th class="n">Median</th><th>Equipment</th><th>Source</th></tr></thead><tbody>
        ${d.evidence.map((e) => `<tr><td>${esc(e.name)}</td><td class="n">${fmt(e.value, 2)} ${esc(e.unit)}</td><td class="n">${fmt(e.median, 2)}</td><td>${esc(e.transformer || "—")}</td><td class="tiny faint">${esc(e.source)}</td></tr>`).join("")}</tbody></table></div></div>
      <div class="panel"><h3>Engineer notes</h3>${d.notes.length ? d.notes.map((n) => `<div class="sig"><div class="top"><b>${esc(n.author)}</b><span class="badge c-NA">${esc(n.status)}</span></div><div class="o">${esc(n.note)}</div></div>`).join("") : '<div class="faint tiny">No notes yet.</div>'}
        ${canNote ? `<div class="sp"></div><textarea class="field" id="noteTxt" rows="2" style="width:100%" placeholder="Add an investigation note…" maxlength="4000"></textarea><div class="row" style="margin-top:8px"><select class="field" id="noteSt"><option>OPEN</option><option>REVIEWED</option><option>DISMISSED</option></select><button class="btn btn-sm btn-primary right" id="noteBtn">Save note</button></div>` : '<div class="tiny faint" style="margin-top:6px">Sign in as an ENGINEER to add notes.</div>'}</div>
    </div>
    <div class="panel ai-panel glass">
      <div class="ai-head">AI INVESTIGATION</div>
      <p style="margin:10px 0 6px;font-size:15px">“<span>${esc(d.headline)}</span>”</p>
      <div class="row" style="align-items:center">${gauge(d.risk_score, d.risk_category)}<div style="flex:1">
        <div class="mono tiny faint">CONFIDENCE</div><div class="mono" style="font-size:26px;font-weight:700">${fmt(d.confidence, 0)}%</div>
        <div class="tiny dim">IF ${fmt(d.components.iforest, 0)} · AE ${fmt(d.components.autoencoder, 0)} · TW-AE ${fmt(d.components.temporal_ae, 0)} · rules ${fmt(d.rule_score, 0)}</div></div></div>
      <div class="qa" style="margin:6px 0 12px">
        <div><b>What happened</b><p>${esc(say(d.what, d.i18n?.what))}</p></div>
        <div><b>Why it was flagged</b><p>${esc(say(d.why, d.i18n?.why))}</p></div>
        <div><b>How unusual</b><p>${esc(d.how_unusual)} — ${esc(say(d.expected_behaviour, d.i18n?.expected))}</p></div>
        <div><b>What to investigate</b><p>${d.investigate.map((x, i) => esc(say(x, d.i18n?.investigate?.[i]))).join("<br/>")}</p></div></div>
      <h3 class="ph">Contributing signals <span class="hint">not confirmed causes</span></h3>
      ${d.rules.map((r) => `<div class="sig"><div class="top"><b>${esc(r.title)}</b><span class="lvl lvl-High">RULE</span></div><div class="o">${esc(sayRule(r, "msg"))}</div><div class="bar warn"><i style="width:${r.severity * 100}%"></i></div></div>`).join("")}
      ${d.contributing_signals.slice(0, 6).map((x) => `<div class="sig"><div class="top"><b>${esc(x.label)}${x.is_primary ? ' <span class="badge c-WARNING" style="margin-left:4px">PRIMARY</span>' : ""}</b><span class="lvl lvl-${x.level}">${x.level.toUpperCase()}</span></div>
        <div class="o">${esc(say(x.observed, x.observed_i18n))}</div><div class="bar"><i style="width:${(x.contribution_share / maxS) * 100}%"></i></div></div>`).join("")}
      <div class="sp"></div><div class="note"><span>${esc(d.method)}</span><br/><br/><span>${esc(d.risk_note)}</span> <span>${esc(d.data_note)}</span></div>
    </div>
  </div>`;
  bind();
  const L = d.trend.timestamps.map(tsShort), fi = d.trend.timestamps.indexOf(d.trend.focus);
  const draw = () => {
    const on = [...document.querySelectorAll("#trSel input:checked")].map((e) => +e.dataset.i);
    const sets = [];
    on.forEach((i) => { const s = d.trend.series[i]; sets.push({ label: `${s.name} (${s.unit})`, data: s.values, color: SERIES[i], w: 2.2 },
      { label: `${s.name} baseline`, data: s.values.map(() => s.baseline_median), color: SERIES[i], dash: [4, 4], w: 1, points: 0 }); });
    line("iT", L, sets, { focus: fi });
  };
  draw(); document.querySelectorAll("#trSel input").forEach((e) => (e.onchange = draw));
  line("iR", L, [{ label: "Anomaly score", data: d.trend.anomaly, color: "#38c8e8" }, riskSet(d.trend.risk)], { focus: fi, y2: "risk", min: 0, max: 100 });
  const tl = d.trend.timestamps, i = tl.indexOf(t);
  document.getElementById("prevH").onclick = () => i > 0 && goInv(sid, tl[i - 1]);
  document.getElementById("nextH").onclick = () => i < tl.length - 1 && goInv(sid, tl[i + 1]);
  const nb = document.getElementById("noteBtn");
  if (nb) nb.onclick = async () => {
    const note = document.getElementById("noteTxt").value.trim(); if (!note) return;
    await api("/investigations/notes", { method: "POST", body: { substation: sid, timestamp: t, status: document.getElementById("noteSt").value, note } });
    toast({ title: "NOTE SAVED", text: "Investigation note recorded (audit-logged).", color: "#3cc483", ttl: 3000 }); investigate(sid, t);
  };
}

// ======================================================================== FLEET
let fleetSort = "risk";
export async function fleet() {
  const f = await api("/fleet", { params: { sort: fleetSort } });
  const hb = (v) => v == null ? '<span class="faint">not logged</span>' : `<span class="mono" style="color:${riskColorVal(100 - v)}">${fmt(v, 0)}</span>`;
  $v().innerHTML = `
  <div class="page-head"><div><h1>Fleet Intelligence</h1><div class="sub">All 24 substations in the source workbooks · health indicators are deviations from each substation's learned baseline</div></div>
    <div class="tabs">${[["risk", "Highest risk"], ["newest", "Newest anomaly"], ["temperature", "Temperature"], ["loading", "Loading"]].map(([k, l]) => `<button data-sort="${k}" class="${fleetSort === k ? "on" : ""}">${l}</button>`).join("")}</div></div>
  <div class="fleet">${f.items.map((s) => s.available ? `<div class="fcard" style="color:${color(s.risk_category)}" data-sid="${s.substation_id}">
      <div class="row"><span class="nm">${esc(s.name)}</span><span class="right">${badge(s.risk_category)}</span></div>
      <div class="hl"><span>AI risk</span><b class="mono" style="color:var(--text)">${fmt(s.risk_score, 0)}</b><span>Anomaly score</span><span class="mono">${fmt(s.anomaly_score, 0)}</span>
        <span>Voltage health</span>${hb(s.voltage_health)}<span>Load health</span>${hb(s.load_health)}<span>Temperature health</span>${hb(s.temperature_health)}
        <span>Last event</span><span class="mono tiny">${s.last_event ? tsShort(s.last_event) : "—"}</span></div>
      <div class="tiny faint" style="margin-top:8px">${s.records} records · ${esc(s.validation)}${s.low_confidence ? " · low confidence" : ""}</div></div>`
    : `<div class="fcard nodata"><div class="nm" style="color:var(--dim)">${esc(s.name)}</div><div style="margin-top:10px"><span class="badge c-NA">NO SOURCE READINGS</span></div><div class="tiny faint" style="margin-top:8px">Data unavailable in supplied records</div></div>`).join("")}</div>`;
  document.querySelectorAll("[data-sort]").forEach((b) => (b.onclick = () => { fleetSort = b.dataset.sort; fleet(); }));
  document.querySelectorAll(".fcard[data-sid]").forEach((c) => (c.onclick = () => { window.selectSub(c.dataset.sid); location.hash = "#/digital"; }));
}

// ======================================================================== ANALYTICS
const AF = { start: "", end: "", parameter: "" };
export async function analytics() {
  const sid = S.sid;
  if (!sub(sid).has_model) { $v().innerHTML = noData(sid); return; }
  $v().innerHTML = skeleton(4, 160);
  const a = await api("/analytics", { params: { substation: sid, start: AF.start && AF.start + "T00:00:00", end: AF.end && AF.end + "T24:00:00", parameter: AF.parameter } });
  const ev = a.evaluation || {}, dates = (sub(sid).days || []);
  const heat = (v) => { const x = Math.abs(v), c = v >= 0 ? "56,200,232" : "240,154,62"; return `background:rgba(${c},${x * .8});color:${x > .5 ? "#031018" : "#e4eaf1"}`; };
  $v().innerHTML = `
  <div class="page-head"><div><h1>Analytics · ${esc(a.substation.name)}</h1><div class="sub">${a.series.timestamps.length} hourly records · ${esc(a.substation.validation || "")}</div></div>
    <div class="row wrap"><select class="field" id="aS">${["", ...dates].map((d) => `<option value="${d}" ${AF.start === d ? "selected" : ""}>${d ? "From " + d : "All dates"}</option>`).join("")}</select>
      <select class="field" id="aE">${["", ...dates].map((d) => `<option value="${d}" ${AF.end === d ? "selected" : ""}>${d ? "To " + d : "To end"}</option>`).join("")}</select>
      <select class="field" id="aP" style="max-width:260px"><option value="">Parameter…</option>${a.parameters.map((p) => `<option value="${esc(p)}" ${AF.parameter === p ? "selected" : ""}>${esc(p.split("|").pop().trim())}</option>`).join("")}</select></div></div>
  <div class="grid g3">
    <div class="panel"><h3>Risk distribution</h3><div class="chart short"><canvas id="aRD"></canvas></div></div>
    <div class="panel"><h3>Anomaly score distribution</h3><div class="chart short"><canvas id="aAH"></canvas></div></div>
    <div class="panel"><h3>Unsupervised evaluation <span class="hint">no labels → no accuracy</span></h3><table><tbody>
      <tr><td>Validation</td><td class="n">${esc(ev.validation || "—")}</td></tr><tr><td>Seed stability (ρ)</td><td class="n">${fmt(ev.seed_stability_spearman, 3)}</td></tr>
      <tr><td>Out-of-sample vs in-sample (ρ)</td><td class="n">${fmt(ev.lodo_vs_in_sample_spearman, 3)}</td></tr><tr><td>Mean confidence</td><td class="n">${fmt(ev.mean_confidence, 0)}%</td></tr>
      <tr><td>IF vs AE agreement (ρ)</td><td class="n">${fmt(ev.component_agreement?.iforest_vs_autoencoder, 2)}</td></tr></tbody></table></div>
  </div><div class="sp"></div>
  <div class="panel"><h3>Anomaly trend &amp; timeline <span class="hint">markers = WARNING+ hours</span></h3><div class="chart"><canvas id="aR"></canvas></div></div><div class="sp"></div>
  ${AF.parameter ? `<div class="panel"><h3>${esc(AF.parameter)}</h3><div class="chart"><canvas id="aSel"></canvas></div></div><div class="sp"></div>` : ""}
  <div class="grid g3">
    <div class="panel"><h3>Voltage trends</h3><div class="chart"><canvas id="aV"></canvas></div></div>
    <div class="panel"><h3>Loading trends</h3><div class="chart"><canvas id="aL"></canvas></div></div>
    <div class="panel"><h3>Temperature trends</h3><div class="chart"><canvas id="aT"></canvas></div></div></div><div class="sp"></div>
  <div class="grid g2">
    <div class="panel"><h3>Equipment health <span class="hint">loading vs nameplate rating (parsed from sheet headers)</span></h3><table><thead><tr><th>Equipment</th><th class="n">Rating</th><th class="n">Peak load</th><th class="n">Peak %</th><th class="n">Load factor</th><th class="n">Max wdg °C</th></tr></thead><tbody>
      ${a.equipment_health.map((e) => `<tr><td>${esc(e.equipment)}</td><td class="n">${e.rating_mva ? e.rating_mva + " MVA" : "—"}</td><td class="n">${fmt(e.peak_load_mva, 1)}</td><td class="n">${fmt(e.peak_loading_pct, 0)}${e.peak_loading_pct != null ? "%" : ""}</td><td class="n">${fmt(e.load_factor, 2)}</td><td class="n">${fmt(e.max_winding_temp, 0)}</td></tr>`).join("")}</tbody></table></div>
    <div class="panel"><h3>Top contributing signals <span class="hint">attribution share over WATCH+ hours</span></h3><div class="chart tall"><canvas id="aTop"></canvas></div></div>
    <div class="panel"><h3>Parameter correlation</h3><div style="overflow:auto"><table class="heat"><thead><tr><th></th>${a.correlation.labels.map((l) => `<th title="${esc(l)}">${esc(l)}</th>`).join("")}</tr></thead>
      <tbody>${a.correlation.matrix.map((r, i) => `<tr><th title="${esc(a.correlation.labels[i])}">${esc(a.correlation.labels[i])}</th>${r.map((v) => `<td style="${heat(v)}">${v.toFixed(2)}</td>`).join("")}</tr>`).join("")}</tbody></table></div></div>
    <div class="panel"><h3>Anomaly timeline</h3><div class="tbl" style="max-height:300px"><table><tbody>${a.anomaly_timeline.map((x) => `<tr class="click" data-inv="${sid}|${x.timestamp}"><td class="mono">${ts(x.timestamp)}</td><td>${badge(x.category)}</td><td class="n">${fmt(x.risk, 0)}</td><td class="tiny dim">${x.rules.join(", ")}</td></tr>`).join("") || `<tr><td>${emptyState("No WARNING+ hours in range")}</td></tr>`}</tbody></table></div></div>
  </div>`;
  bind();
  const rd = a.risk_distribution; bars("aRD", Object.keys(rd), Object.values(rd), Object.keys(rd).map(color));
  const h = a.anomaly_histogram; bars("aAH", h.counts.map((_, i) => `${h.edges[i]}`), h.counts, "#38c8e8", { x: "anomaly score" });
  const L = a.series.timestamps.map(tsShort), sg = a.series.signals;
  line("aR", L, [{ label: "Anomaly score", data: a.series.anomaly, color: "#38c8e8", fill: "rgba(56,200,232,.06)" }, riskSet(a.series.risk)], { y2: "risk", min: 0, max: 100 });
  line("aV", L, sg.voltages.slice(0, 4).map((s) => ({ label: s.name, data: s.values })));
  line("aL", L, sg.transformer_loads.slice(0, 4).map((s) => ({ label: s.name, data: s.values })));
  const temps = sg.transformer_temperature.length ? sg.transformer_temperature : sg.oil_temperature;
  if (temps.length) line("aT", L, temps.slice(0, 6).map((s) => ({ label: s.name, data: s.values }))); else document.getElementById("aT").parentElement.innerHTML = emptyState("Not logged at this substation.");
  if (AF.parameter && sg.selected) line("aSel", L, sg.selected.map((s) => ({ label: `${s.name} (${s.unit})`, data: s.values })));
  bars("aTop", a.top_contributing_signals.map((x) => x.label.length > 44 ? x.label.slice(0, 42) + "…" : x.label), a.top_contributing_signals.map((x) => x.weight), "#f09a3e", { h: true });
  const re = () => { AF.start = document.getElementById("aS").value; AF.end = document.getElementById("aE").value; AF.parameter = document.getElementById("aP").value; analytics(); };
  ["aS", "aE", "aP"].forEach((i) => (document.getElementById(i).onchange = re));
}

// ======================================================================== MODEL LAB
export async function models() {
  const m = await api("/models");
  const ev = m.evaluation || {}, subsEv = ev.substations || {}, rev = ev.reviewed_events || [];
  const md = m.models;
  const card = (k, title) => { const x = md[k]; return `<div class="panel"><h3>${esc(title)} <span>${x.status === "trained" ? '<span class="badge c-NORMAL">TRAINED</span>' : '<span class="badge c-NA">NOT TRAINED</span>'}</span></h3>
    <div class="mono" style="font-size:15px">${esc(x.name)}</div><div class="tiny dim">${x.version ? "v" + esc(x.version) + " · " : ""}${x.created_at ? ts(x.created_at.slice(0, 19)) + " UTC" : ""}</div>
    ${x.config ? `<div class="sp"></div><table><tbody>${Object.entries(x.config).map(([a, b]) => `<tr><td class="faint">${esc(a)}</td><td class="mono tiny">${esc(b)}</td></tr>`).join("")}</tbody></table>` : `<p class="dim tiny">${esc(x.reason || "")}</p>`}
    ${m.component_score_summary[{ isolation_forest: "iforest", autoencoder: "autoencoder", temporal_autoencoder: "temporal_ae" }[k]] ? `<div class="tiny faint" style="margin-top:8px">calibrated score mean ${fmt(m.component_score_summary[{ isolation_forest: "iforest", autoencoder: "autoencoder", temporal_autoencoder: "temporal_ae" }[k]].mean, 1)}</div>` : ""}</div>`; };
  $v().innerHTML = `
  <div class="page-head"><div><h1>AI Model Lab</h1><div class="sub">${esc(m.ensemble.name)} · trained ${ts(m.ensemble.created_at.slice(0, 19))} UTC · run <span class="mono">${esc(m.ensemble.run_id)}</span></div></div>
    <span class="badge c-WATCH">${esc(m.evaluation_mode)}</span></div>
  <div class="kpis">
    <div class="kpi"><div class="k">Current model</div><div class="v" style="font-size:18px">Ensemble v${esc(m.ensemble.version)}</div><div class="s">IF ${m.ensemble.weights.iforest} · AE ${m.ensemble.weights.autoencoder} · TW-AE ${m.ensemble.weights.temporal_ae} + rules v${esc(m.ensemble.rules_version)}</div></div>
    <div class="kpi"><div class="k">Training data</div><div class="v" style="font-size:18px">Dataset A</div><div class="s">${esc(m.ensemble.validation)}</div></div>
    <div class="kpi"><div class="k">Artifacts</div><div class="v">${m.artifacts.length}</div><div class="s">fold + production models, SHA-256 registered</div></div>
    <div class="kpi"><div class="k">Inference latency</div><div class="v">${m.inference_latency_ms.p50 == null ? "—" : fmt(m.inference_latency_ms.p50, 1) + "ms"}</div><div class="s">p95 ${fmt(m.inference_latency_ms.p95, 1)} ms · ${m.inference_latency_ms.samples} samples</div></div>
    <div class="kpi"><div class="k">Reviewed events flagged</div><div class="v">${ev.summary?.reviewed_events_flagged_warning_or_above ?? "—"}/${ev.summary?.reviewed_events_total ?? "—"}</div><div class="s">out-of-sample, WARNING or above</div></div></div>
  <div class="sp"></div>
  <div class="grid g3">${card("isolation_forest", "Isolation Forest")}${card("autoencoder", "Autoencoder")}${card("temporal_autoencoder", "Temporal-window AE")}</div><div class="sp"></div>
  <div class="grid g2">${card("lstm_autoencoder", "LSTM Autoencoder")}${card("supervised", "Supervised (XGBoost / LightGBM)")}</div><div class="sp"></div>
  <div class="grid g2">
    <div class="panel"><h3>Anomaly distribution <span class="hint">all scored hours, out-of-sample</span></h3><div class="chart short"><canvas id="mA"></canvas></div></div>
    <div class="panel"><h3>Reviewed real events <span class="hint">validation on unseen days</span></h3>${rev.map((e) => `<div class="sig"><div class="top"><b>${esc(e.substation)} · ${ts(e.timestamp)}</b>${badge(e.category)}</div><div class="o">${esc(e.observation)} — risk ${fmt(e.risk, 0)}, anomaly ${fmt(e.anomaly_score, 0)}, confidence ${fmt(e.confidence, 0)}%, rules ${esc(e.rules.join(", ") || "none")}, model ${esc(e.model)}</div></div>`).join("")}</div></div>
  <div class="sp"></div>
  <div class="panel"><h3>Validation results by substation <span class="hint">unsupervised evaluation</span></h3><div class="tbl"><table><thead><tr><th>Substation</th><th>Validation</th><th class="n">Records</th><th class="n">Seed ρ</th><th class="n">OOS vs IS ρ</th><th class="n">IF–AE ρ</th><th class="n">IF–TW ρ</th><th class="n">Conf.</th><th>Categories</th></tr></thead><tbody>
    ${Object.entries(subsEv).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="tiny">${esc(v.validation)}</td><td class="n">${v.records}</td><td class="n">${fmt(v.seed_stability_spearman, 3)}</td><td class="n">${fmt(v.lodo_vs_in_sample_spearman, 3)}</td><td class="n">${fmt(v.component_agreement?.iforest_vs_autoencoder, 2)}</td><td class="n">${fmt(v.component_agreement?.iforest_vs_temporal_ae, 2)}</td><td class="n">${fmt(v.mean_confidence, 0)}</td>
      <td>${Object.entries(v.risk_category_counts).map(([c, n]) => `<span class="chip ${cls(c)}">${c} ${n}</span>`).join("")}</td></tr>`).join("")}</tbody></table></div></div>
  <div class="sp"></div>
  ${Object.keys(m.benchmarks || {}).length ? `<div class="panel"><h3>Public benchmarks <span class="hint">method validation — not HVPNL data</span></h3>${Object.entries(m.benchmarks).map(([k, b]) => `<div class="sig"><div class="top"><b>${esc(k)}</b><span class="tiny faint">${esc(b.license || "")}</span></div><div class="o">${esc(b.summary)}</div></div>`).join("")}</div><div class="sp"></div>` : ""}
  <div class="panel"><h3>Model artifacts <span class="hint">models/registry.json</span></h3><div class="tbl" style="max-height:280px"><table><thead><tr><th>Substation</th><th>Key</th><th>Trained days</th><th class="n">Features</th><th>Fingerprint</th><th>SHA-256</th></tr></thead><tbody>
    ${m.artifacts.map((x) => `<tr><td>${esc(x.substation)}</td><td class="mono">${esc(x.key)}</td><td class="tiny">${esc(x.trained_days.join(", "))}</td><td class="n">${x.n_features}</td><td class="mono tiny">${esc(x.fingerprint)}</td><td class="mono tiny faint">${esc(x.sha256.slice(0, 16))}…</td></tr>`).join("")}</tbody></table></div></div>
  <div class="sp"></div><div class="note">${esc(m.risk_note)} ${esc(m.disclaimer)}</div>`;
  const h = m.anomaly_distribution; bars("mA", h.counts.map((_, i) => `${h.edges[i]}–${h.edges[i + 1]}`), h.counts, h.edges.slice(0, -1).map((e) => riskColorVal(e + 5)));
}

// ======================================================================== DATA EXPLORER
const EX = { parameter: "", date: "", hour: "", page: 1 };
export async function explorer() {
  const sid = S.sid;
  if (!sub(sid).has_model) { $v().innerHTML = noData(sid); return; }
  const params = await api("/parameters", { params: { substation: sid, size: 500 } });
  const usable = params.items.filter((p) => p.numeric_pct > 0);
  if (!EX.parameter || !usable.find((p) => p.parameter === EX.parameter)) EX.parameter = usable.find((p) => /220 kV Bus-I|Bus I/i.test(p.parameter))?.parameter || usable[0]?.parameter;
  const q = { substation: sid, parameter: EX.parameter, date: EX.date, hour: EX.hour, page: EX.page, size: 50 };
  const d = await api("/explorer", { params: q });
  const pages = Math.max(1, Math.ceil(d.total / 50));
  $v().innerHTML = `
  <div class="page-head"><div><h1>Data Explorer · ${esc(sub(sid).name)}</h1><div class="sub">${esc(d.note)}</div></div>
    <button class="btn btn-primary btn-sm" id="exCsv">⤓ Export CSV</button></div>
  <div class="panel"><div class="row wrap">
    <select class="field" id="exP" style="max-width:420px">${usable.map((p) => `<option value="${esc(p.parameter)}" ${p.parameter === EX.parameter ? "selected" : ""}>${esc(p.parameter)} (${esc(p.unit)})</option>`).join("")}</select>
    <select class="field" id="exD"><option value="">All dates</option>${(sub(sid).days || []).map((x) => `<option ${EX.date === x ? "selected" : ""}>${x}</option>`).join("")}</select>
    <select class="field" id="exH"><option value="">All hours</option>${Array.from({ length: 24 }, (_, i) => i + 1).map((x) => `<option value="${x}" ${+EX.hour === x ? "selected" : ""}>${String(x).padStart(2, "0")}:00</option>`).join("")}</select>
    <span class="right tiny dim">${d.total} rows · page ${EX.page}/${pages}</span></div></div>
  <div class="sp"></div>
  <div class="panel"><h3>${esc(EX.parameter)} <span class="hint">cleaned value · 3 h rolling mean</span></h3><div class="chart short"><canvas id="exC"></canvas></div></div><div class="sp"></div>
  <div class="panel"><div class="tbl"><table><thead><tr><th>Timestamp</th><th>Raw cell</th><th class="n">Cleaned</th><th class="n">Roll. mean 3h</th><th class="n">Roll. std 3h</th><th class="n">Anomaly</th><th class="n">Risk</th><th>Category</th></tr></thead><tbody>
    ${d.items.map((r) => `<tr class="click" data-inv="${sid}|${r.timestamp}"><td class="mono">${ts(r.timestamp)}</td><td class="mono">${esc(r.raw_value ?? "∅")}</td><td class="n">${fmt(r.cleaned_value, 2)}</td><td class="n">${fmt(r.rolling_mean_3h, 2)}</td><td class="n">${fmt(r.rolling_std_3h, 2)}</td><td class="n">${fmt(r.anomaly_score, 0)}</td><td class="n">${fmt(r.risk_score, 0)}</td><td>${badge(r.risk_category)}</td></tr>`).join("")}</tbody></table></div>
    <div class="row" style="margin-top:10px;justify-content:flex-end"><button class="btn btn-sm" id="exPrev" ${EX.page <= 1 ? "disabled" : ""}>← Prev</button><button class="btn btn-sm" id="exNext" ${EX.page >= pages ? "disabled" : ""}>Next →</button></div></div>`;
  bind();
  line("exC", d.items.map((r) => tsShort(r.timestamp)), [{ label: "cleaned", data: d.items.map((r) => r.cleaned_value), color: "#38c8e8" }, { label: "rolling mean 3h", data: d.items.map((r) => r.rolling_mean_3h), color: "#f0c06a", dash: [4, 3], points: 0 }]);
  const re = () => { EX.parameter = document.getElementById("exP").value; EX.date = document.getElementById("exD").value; EX.hour = document.getElementById("exH").value; EX.page = 1; explorer(); };
  ["exP", "exD", "exH"].forEach((i) => (document.getElementById(i).onchange = re));
  document.getElementById("exPrev").onclick = () => { EX.page--; explorer(); };
  document.getElementById("exNext").onclick = () => { EX.page++; explorer(); };
  document.getElementById("exCsv").onclick = async () => {
    const r = await api("/explorer/export.csv", { params: { substation: sid, parameter: EX.parameter, date: EX.date, hour: EX.hour }, raw: true });
    download(`${sid}_${EX.parameter.split("|").pop().trim().replace(/\W+/g, "_")}.csv`, await r.blob());
    toast({ title: "EXPORT", text: "CSV downloaded (audit-logged).", color: "#3cc483", ttl: 3000 });
  };
}
