// Mobile i18n — English, Hindi, Haryanvi, Punjabi. Same table and rules as the web app (frontend/assets/js/i18n.js):
// English UI text is the key; API sentences come with [template key, args] pairs. Source data is never translated.
import React from "react";
import { Platform, StyleSheet, Text as RNText } from "react-native";
import { LANGS, STRINGS } from "./strings";

export { LANGS };
const KEY = "gi_lang";
const index = new Map();
const patterns = [];
for (const [k, row] of Object.entries(STRINGS)) {
  if (/^[a-z]+\.[A-Za-z0-9_.-]+$/.test(k)) continue;
  if (/\{\w+\}/.test(k)) {
    const names = [];
    const src = k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\\\{(\w+)\\\}/g, (_, n) => { names.push(n); return "(.+?)"; });
    patterns.push({ re: new RegExp("^" + src + "$", "i"), names, row });
  } else index.set(k.toLowerCase(), row);
}

const store = {
  get() { try { return Platform.OS === "web" && typeof localStorage !== "undefined" ? localStorage.getItem(KEY) : null; } catch { return null; } },
  set(v) { try { if (Platform.OS === "web" && typeof localStorage !== "undefined") localStorage.setItem(KEY, v); } catch { /* blocked */ } },
};
let lang = store.get();
if (!LANGS.some((l) => l.code === lang)) lang = "en";
const subs = new Set();

export const getLang = () => lang;
export function setLang(code) {
  if (!LANGS.some((l) => l.code === code) || code === lang) return;
  lang = code; store.set(code); subs.forEach((f) => f(code));
}
export function useLang() {
  const [l, set] = React.useState(lang);
  React.useEffect(() => { subs.add(set); return () => subs.delete(set); }, []);
  return l;
}

const fill = (tpl, args) => tpl.replace(/\{(\w+)\}/g, (m, n) => (args && n in args ? arg(args[n]) : m));
const arg = (v) => (typeof v === "string" ? phrase(v) : v == null ? "" : String(v));

function lookup(s) {
  const row = index.get(s.toLowerCase());
  if (row) return row[lang] || row.en;
  for (const p of patterns) {
    const m = p.re.exec(s);
    if (m) { const a = {}; p.names.forEach((n, i) => (a[n] = m[i + 1])); return fill(p.row[lang] || p.row.en, a); }
  }
  return null;
}

export function phrase(s) {
  if (lang === "en" || typeof s !== "string" || !s) return s;
  const core = s.trim();
  if (!core || !/[A-Za-z]/.test(core)) return s;
  const at = s.indexOf(core), lead = s.slice(0, at), trail = s.slice(at + core.length);
  let out = lookup(core);
  if (out == null) { const m = /^(.*?)([:…]+)$/.exec(core); if (m && lookup(m[1])) out = lookup(m[1]) + m[2]; }
  if (out == null) {
    for (const sep of [" · ", " — ", " | "]) {
      if (core.includes(sep)) {
        const parts = core.split(sep), tr = parts.map(phrase);
        if (tr.some((t, i) => t !== parts[i])) { out = tr.join(sep); break; }
      }
    }
  }
  return out == null ? s : lead + out + trail;
}

export function t(key, args) {
  const row = STRINGS[key];
  return row ? fill(row[lang] || row.en, args || {}) : phrase(key);
}
export function tr(english, pair) {
  if (lang === "en" || !Array.isArray(pair) || !STRINGS[pair[0]]) return phrase(english || "");
  return t(pair[0], pair[1]);
}

// Drop-in <Text>: translates plain string children; pass noTranslate for source data (names, values).
const mapKids = (c) => (typeof c === "string" ? phrase(c) : Array.isArray(c) ? c.map(mapKids) : c);
// Letter-spacing breaks Devanagari/Gurmukhi conjuncts, so it is dropped outside English.
export function Text({ children, noTranslate, style, ...rest }) {
  if (noTranslate || lang === "en") return <RNText style={style} {...rest}>{children}</RNText>;
  const st = style ? { ...StyleSheet.flatten(style), letterSpacing: 0 } : style;
  return <RNText style={st} {...rest}>{mapKids(children)}</RNText>;
}
