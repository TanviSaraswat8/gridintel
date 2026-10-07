// GridIntel field app service worker: shows alert notifications (Web Push) and opens the investigation on tap.
// It does not cache anything — the app always loads the current version from the server.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let m = {};
  try { m = event.data ? event.data.json() : {}; } catch (e) { m = { title: "GridIntel", body: event.data && event.data.text() }; }
  const urgent = m.category === "CRITICAL" || m.category === "HIGH RISK";
  event.waitUntil(self.registration.showNotification(m.title || "GridIntel alert", {
    body: m.body || "",
    icon: "/mobile/icon-192.png",
    badge: "/mobile/icon-192.png",
    tag: m.tag || "gridintel",
    renotify: true,
    requireInteraction: m.category === "CRITICAL",
    vibrate: urgent ? [200, 100, 200, 100, 400] : [150],
    data: { url: m.url || "/mobile/" },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL((event.notification.data && event.notification.data.url) || "/mobile/", self.location.origin).href;
  event.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const open = all.find((c) => c.url.startsWith(self.location.origin + "/mobile"));
    if (open) { await open.focus(); open.postMessage({ type: "open", url }); return; }
    await self.clients.openWindow(url);
  })());
});
