// Landing page: schematic grid network (illustrative) + aggregate stats from the public API endpoint.
(function () {
  const API = ((window.GRIDINTEL_CONFIG && window.GRIDINTEL_CONFIG.API_URL) || "").replace(/\/$/, "");
  const svg = document.getElementById("gridViz");
  const NS = "http://www.w3.org/2000/svg";
  const el = (tag, attrs, parent) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); (parent || svg).appendChild(e); return e; };

  // schematic: 220 kV source bus → two 220 kV substations → transformers → 66 kV / 11 kV feeders
  const C = { n: "#3cc483", w: "#e9c04a", r: "#f0544f", line: "#5fa8ff" };
  el("text", { x: 20, y: 28, class: "vlabel" }).textContent = "SCHEMATIC · 220 kV → 66 kV → 11 kV";
  el("line", { x1: 40, y1: 70, x2: 600, y2: 70, class: "wire hv" });
  el("text", { x: 40, y: 60, class: "vtag" }).textContent = "220 kV GRID";
  const subs = [{ x: 170, name: "220 kV SS-A", tx: ["T-3", "T-4"], st: ["n", "n"] }, { x: 470, name: "220 kV SS-B", tx: ["T-1", "T-2"], st: ["n", "w"] }];
  subs.forEach((s, si) => {
    el("line", { x1: s.x, y1: 70, x2: s.x, y2: 120, class: "wire hv" });
    el("path", { d: `M${s.x} 70 V120`, class: "flowdash" });
    const g = el("g", { class: "vnode" });
    el("rect", { x: s.x - 70, y: 120, width: 140, height: 34, rx: 6, fill: "rgba(18,25,34,.95)", stroke: "rgba(95,168,255,.5)" }, g);
    el("text", { x: s.x, y: 142, "text-anchor": "middle", class: "vlabel" }, g).textContent = s.name;
    s.tx.forEach((t, i) => {
      const x = s.x - 45 + i * 90;
      el("line", { x1: x, y1: 154, x2: x, y2: 210, class: "wire" });
      el("path", { d: `M${x} 154 V210`, class: "flowdash", style: `animation-delay:${-(si + i) * 0.5}s` });
      const tg = el("g", { class: "vnode" });
      el("circle", { cx: x, cy: 228, r: 16, fill: "rgba(12,17,23,1)", stroke: C[s.st[i]], "stroke-width": 2 }, tg);
      el("circle", { cx: x, cy: 238, r: 16, fill: "none", stroke: C[s.st[i]], "stroke-width": 2, opacity: .7 }, tg);
      el("text", { x: x + 24, y: 236, class: "vtag" }, tg).textContent = t;
      el("line", { x1: x, y1: 254, x2: x, y2: 300, class: "wire" });
      el("line", { x1: x - 40, y1: 300, x2: x + 40, y2: 300, class: "wire" });
      for (let k = 0; k < 3; k++) {
        const fx = x - 30 + k * 30;
        const st = s.st[i] === "w" && k === 1 ? "w" : "n";
        el("line", { x1: fx, y1: 300, x2: fx, y2: 352, class: "wire" });
        el("path", { d: `M${fx} 300 V352`, class: "flowdash", style: `animation-delay:${-k * 0.3}s` });
        el("rect", { x: fx - 6, y: 352, width: 12, height: 12, rx: 2, fill: C[st], opacity: .9 });
      }
    });
    el("text", { x: s.x, y: 392, "text-anchor": "middle", class: "vtag" }).textContent = "11 kV FEEDERS";
  });
  // AI layer
  const ai = el("g", {});
  el("rect", { x: 120, y: 420, width: 400, height: 64, rx: 10, fill: "rgba(56,200,232,.06)", stroke: "rgba(56,200,232,.45)" }, ai);
  el("text", { x: 320, y: 446, "text-anchor": "middle", class: "vlabel", fill: "#38c8e8" }, ai).textContent = "AI ANOMALY ENGINE";
  el("text", { x: 320, y: 466, "text-anchor": "middle", class: "vtag" }, ai).textContent = "IForest · Autoencoder · Temporal AE · Rules → risk · confidence";
  [130, 210, 290, 350, 430, 510].forEach((x, i) => {
    el("path", { d: `M${x} 370 C ${x} 400, 320 395, 320 420`, class: "wire", opacity: .5 });
    el("path", { d: `M${x} 370 C ${x} 400, 320 395, 320 420`, class: "flowdash", style: `animation-delay:${-i * 0.37}s;opacity:.5` });
  });

  // stats (aggregate only; no measurements)
  fetch(API + "/api/v1/public/stats").then((r) => r.json()).then((s) => {
    const set = (k, v) => { const e = document.querySelector(`[data-k="${k}"]`); if (e) e.textContent = v; };
    set("substations_monitored", `${s.substations_monitored}/${s.sheets_in_source}`);
    set("hourly_records", s.hourly_records.toLocaleString());
    set("parameters_ingested", s.parameters_ingested.toLocaleString());
    set("models_n", s.models.length);
    set("replay_mode", s.replay_mode === "RUNNING" ? "RUNNING" : "READY");
  }).catch(() => {
    document.querySelectorAll(".stat .v").forEach((e) => (e.textContent = "offline"));
  });
})();
