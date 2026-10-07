// Alert notifications for the browser/installed build (Web Push). Native builds would use expo-notifications instead.
import { Platform } from "react-native";
import { api } from "./api";
import { getLang } from "./i18n";

const SW = "/mobile/sw.js";
const web = Platform.OS === "web" && typeof window !== "undefined";

export const supported = () => web && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
// iPhone/iPad only allow web push for apps added to the Home Screen (iOS 16.4+)
export const isIOS = () => web && /iPad|iPhone|iPod/.test(navigator.userAgent);
export const standalone = () => web && (window.matchMedia?.("(display-mode: standalone)").matches || navigator.standalone === true);

export function register() {
  if (!supported()) return;
  navigator.serviceWorker.register(SW, { scope: "/mobile/" }).catch(() => {});
}

// tap on a notification while the app is open → the service worker posts the investigation URL
export function onOpen(cb) {
  if (!web || !("serviceWorker" in navigator)) return () => {};
  const h = (e) => { if (e.data && e.data.type === "open") cb(e.data.url); };
  navigator.serviceWorker.addEventListener("message", h);
  return () => navigator.serviceWorker.removeEventListener("message", h);
}

// "?inv=<substation>|<timestamp>" from a notification tap that opened the app
export function pendingInvestigation() {
  if (!web) return null;
  const v = new URLSearchParams(window.location.search).get("inv");
  if (!v || !v.includes("|")) return null;
  const [sid, ts] = v.split("|");
  window.history.replaceState(null, "", window.location.pathname);
  return { sid, ts };
}
export function parseInv(url) {
  try { const v = new URL(url).searchParams.get("inv"); if (v && v.includes("|")) { const [sid, ts] = v.split("|"); return { sid, ts }; } } catch {}
  return null;
}

const toKey = (b64) => { const s = (b64 + "=".repeat((4 - (b64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(s), (c) => c.charCodeAt(0)); };

async function current() {
  const reg = await navigator.serviceWorker.getRegistration("/mobile/");
  return reg ? reg.pushManager.getSubscription() : null;
}

export async function status() {
  if (!supported()) return { supported: false };
  const sub = await current();
  return { supported: true, permission: Notification.permission, subscribed: !!sub };
}

export async function enable(minCategory) {
  const perm = await Notification.requestPermission();
  if (perm !== "granted") throw new Error("Notifications are blocked for this site. Allow them in the browser or phone settings.");
  const cfg = await api.get("/push/config");
  const reg = await navigator.serviceWorker.register(SW, { scope: "/mobile/" });
  await navigator.serviceWorker.ready;
  let sub = await reg.pushManager.getSubscription();
  if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: toKey(cfg.public_key) });
  const j = sub.toJSON();
  await api.post("/push/subscribe", { endpoint: j.endpoint, keys: j.keys, min_category: minCategory, lang: getLang() });
  return true;
}

export async function disable() {
  const sub = await current();
  if (sub) { await api.post("/push/unsubscribe", { endpoint: sub.endpoint }).catch(() => {}); await sub.unsubscribe(); }
}

export const sendTest = () => api.post("/push/test", {});
