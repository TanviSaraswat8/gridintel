/* GridIntel i18n — English, Hindi, Haryanvi, Punjabi.
 *
 * Strings come from i18n-strings.js (generated from i18n/translations.py). English UI text is the lookup key,
 * so pages are authored in English and translated on the fly:
 *   - a MutationObserver translates text nodes and placeholder/title/aria-label attributes as they appear;
 *   - GI18N.t(key, args) renders template keys such as "rule.R-V1.msg" that the API sends with display-ready args;
 *   - GI18N.tr(english, [key, args]) prefers the template and falls back to the English sentence.
 * Source data (HVPNL parameter names, substation names, numbers) is never translated.
 */
(function () {
  "use strict";
  const STRINGS = window.GI_STRINGS || {};
  const LANGS = window.GI_LANGS || [{ code: "en", name: "English" }];
  const HTML_LANG = { en: "en", hi: "hi", hry: "bgc", pa: "pa" };
  const KEY = "gi_lang";

  // case-insensitive index over plain keys, regexes over pattern keys like "{n} events"
  const index = new Map();
  const patterns = [];
  for (const [k, row] of Object.entries(STRINGS)) {
    if (/^[a-z]+\.[A-Za-z0-9_.-]+$/.test(k)) continue; // template keys are only reached through t()
    if (/\{\w+\}/.test(k)) {
      const names = [];
      const src = k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\\\{(\w+)\\\}/g, (_, n) => { names.push(n); return "(.+?)"; });
      patterns.push({ re: new RegExp("^" + src + "$", "i"), names, row });
    } else {
      index.set(k.toLowerCase(), row);
    }
  }

  let lang = "en";
  try { lang = localStorage.getItem(KEY) || ""; } catch (e) { /* storage blocked */ }
  if (!LANGS.some((l) => l.code === lang)) {
    const nav = (navigator.language || "en").toLowerCase();
    lang = nav.startsWith("pa") ? "pa" : nav.startsWith("hi") ? "hi" : "en";
  }

  const fill = (tpl, args) => tpl.replace(/\{(\w+)\}/g, (m, n) => (args && n in args ? arg(args[n]) : m));
  const arg = (v) => (typeof v === "string" ? phrase(v) : v == null ? "" : String(v));

  function lookup(s) {
    const row = index.get(s.toLowerCase());
    if (row) return row[lang] || row.en;
    for (const p of patterns) {
      const m = p.re.exec(s);
      if (m) {
        const args = {};
        p.names.forEach((n, i) => (args[n] = m[i + 1]));
        return fill(p.row[lang] || p.row.en, args);
      }
    }
    return null;
  }

  // translate a phrase: exact → trailing punctuation → " · " / " — " / " / " segments; unknown text stays as is
  function phrase(s) {
    if (lang === "en" || !s) return s;
    const core = s.trim();
    if (!core || !/[A-Za-z]/.test(core)) return s;
    const lead = s.slice(0, s.indexOf(core)), trail = s.slice(s.indexOf(core) + core.length);
    let out = lookup(core);
    if (out == null) {
      const m = /^(.*?)([:：…]+)$/.exec(core);
      if (m && lookup(m[1])) out = lookup(m[1]) + m[2];
    }
    if (out == null) {
      for (const sep of [" · ", " — ", " | "]) {
        if (core.includes(sep)) {
          const parts = core.split(sep);
          const tr = parts.map((p) => phrase(p));
          if (tr.some((t, i) => t !== parts[i])) { out = tr.join(sep); break; }
        }
      }
    }
    return out == null ? s : lead + out + trail;
  }

  function t(key, args) {
    const row = STRINGS[key];
    if (!row) return phrase(key);
    return fill(row[lang] || row.en, args || {});
  }

  function tr(english, pair) {
    if (lang === "en" || !pair || !Array.isArray(pair) || !STRINGS[pair[0]]) return phrase(english || "");
    return t(pair[0], pair[1]);
  }

  // ------------------------------------------------------------ DOM auto-translation
  const SKIP = new Set(["SCRIPT", "STYLE", "TEXTAREA", "CODE", "PRE", "CANVAS", "SVG", "OPTION_NOI18N"]);
  const ATTRS = ["placeholder", "title", "aria-label"];
  const origText = new WeakMap(); // text node -> English source
  const lastText = new WeakMap(); // text node -> what we last wrote
  const origAttr = new WeakMap(); // element -> {attr: English}
  let writing = false;

  function skip(el) {
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      if (SKIP.has(e.tagName) || e.hasAttribute("data-noi18n") || e.isContentEditable) return true;
    }
    return false;
  }

  function doText(node) {
    const cur = node.data;
    if (!origText.has(node) || lastText.get(node) !== cur) origText.set(node, cur);
    const next = phrase(origText.get(node));
    if (next !== cur) { writing = true; node.data = next; writing = false; }
    lastText.set(node, node.data);
  }

  function doAttrs(el) {
    let o = origAttr.get(el);
    for (const a of ATTRS) {
      if (!el.hasAttribute(a)) continue;
      const cur = el.getAttribute(a);
      if (!o) { o = {}; origAttr.set(el, o); }
      if (!(a in o) || o["_" + a] !== cur) o[a] = cur;
      const next = phrase(o[a]);
      if (next !== cur) { writing = true; el.setAttribute(a, next); writing = false; }
      o["_" + a] = el.getAttribute(a);
    }
  }

  function walk(root) {
    if (!root) return;
    if (root.nodeType === 3) { if (!skip(root.parentElement)) doText(root); return; }
    if (root.nodeType !== 1 || skip(root)) return;
    doAttrs(root);
    const w = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => (n.nodeType === 1 && skip(n) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
    });
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      if (n.nodeType === 3) { if (n.data.trim()) doText(n); } else doAttrs(n);
    }
  }

  const observer = new MutationObserver((muts) => {
    if (writing) return;
    for (const m of muts) {
      if (m.type === "childList") m.addedNodes.forEach(walk);
      else if (m.type === "characterData") { if (!skip(m.target.parentElement)) doText(m.target); }
      else if (m.type === "attributes" && !skip(m.target)) doAttrs(m.target);
    }
  });

  function start() {
    document.documentElement.lang = HTML_LANG[lang] || "en";
    document.documentElement.dataset.lang = lang;
    walk(document.body);
    observer.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });
    document.querySelectorAll("[data-lang-picker]").forEach(mountPicker);
  }

  function setLang(code) {
    if (!LANGS.some((l) => l.code === code) || code === lang) return;
    lang = code;
    try { localStorage.setItem(KEY, code); } catch (e) { /* storage blocked */ }
    document.documentElement.lang = HTML_LANG[lang] || "en";
    document.documentElement.dataset.lang = lang;
    walk(document.body);
    document.querySelectorAll("select.lang-select").forEach((s) => (s.value = lang));
    window.dispatchEvent(new CustomEvent("gi:lang", { detail: { lang } }));
  }

  function mountPicker(host) {
    if (host.querySelector("select.lang-select")) return;
    const sel = document.createElement("select");
    sel.className = "lang-select";
    sel.setAttribute("aria-label", "Language");
    sel.setAttribute("data-noi18n", "");
    for (const l of LANGS) {
      const o = document.createElement("option");
      o.value = l.code; o.textContent = l.name;
      sel.appendChild(o);
    }
    sel.value = lang;
    sel.addEventListener("change", () => setLang(sel.value));
    host.appendChild(sel);
  }

  window.GI18N = { t, tr, phrase, setLang, mountPicker, LANGS, get lang() { return lang; } };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
