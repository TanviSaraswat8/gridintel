// Client for the GridIntel API (/api/v1, JWT bearer auth) — same backend as the web command center.
import { Platform } from "react-native";

function defaultBase() {
  if (process.env.EXPO_PUBLIC_API_URL) return process.env.EXPO_PUBLIC_API_URL;
  if (Platform.OS === "web" && typeof window !== "undefined") return window.location.origin; // web build served at /mobile
  return "http://192.168.1.10:8000"; // set your PC's LAN IP (or the deployed API URL) on the sign-in screen
}

let BASE = defaultBase();
let TOKEN = null;
let onUnauthorized = () => {};

export const getBase = () => BASE;
export const setBase = (b) => { BASE = b.trim().replace(/\/+$/, ""); };
export const setToken = (t) => { TOKEN = t; };
export const setOnUnauthorized = (fn) => { onUnauthorized = fn; };

async function req(method, path, params, body) {
  const q = params
    ? "?" + Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&")
    : "";
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), 10000);
  try {
    const r = await fetch(`${BASE}/api/v1${path}${q}`, {
      method, signal: ctrl.signal,
      headers: { ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}), ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    const txt = await r.text();
    if (r.status === 401 && TOKEN) onUnauthorized();
    if (!r.ok) {
      let msg = txt;
      try { const j = JSON.parse(txt); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch (e) {}
      throw new Error(msg || `HTTP ${r.status}`);
    }
    return JSON.parse(txt);
  } catch (e) {
    if (e.name === "AbortError") throw new Error(`Backend not reachable at ${BASE}`);
    throw e;
  } finally {
    clearTimeout(t);
  }
}

export const api = {
  get: (p, params) => req("GET", p, params),
  post: (p, body) => req("POST", p, null, body || {}),
};
