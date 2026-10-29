/* Web Push service worker. No caching: dashboard and camera data stay live. */
self.addEventListener("push", (event) => {
  let payload = {};
  try { payload = event.data ? event.data.json() : {}; }
  catch { payload = { body: event.data ? event.data.text() : "" }; }
  const title = payload.title || "SMART HOME";
  const url = typeof payload.url === "string" && payload.url.startsWith("/") &&
    !payload.url.startsWith("//") ? payload.url : "/events";
  event.waitUntil(self.registration.showNotification(title, {
    body: payload.body || "Bạn có cảnh báo mới.",
    icon: "/icons/smart-home-192.png",
    badge: "/icons/smart-home-192.png",
    tag: payload.tag || "smart-home",
    data: { url },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(event.notification.data?.url || "/events", self.location.origin);
  if (url.origin !== self.location.origin) return;
  event.waitUntil((async () => {
    const pages = await clients.matchAll({ type: "window", includeUncontrolled: true });
    const existing = pages.find(page => new URL(page.url).origin === url.origin);
    if (existing) {
      await existing.focus();
      return existing.navigate(url.href);
    }
    return clients.openWindow(url.href);
  })());
});
