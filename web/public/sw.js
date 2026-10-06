/*
 * Hangul's service worker: just enough to install, to show a friendly offline
 * page, and to show notifications (Web Push) while Hangul is closed.
 * Deliberately does NOT cache pages or /api responses -- those are private and
 * must always be fresh -- only the offline page and icons.
 */
const CACHE = "hangul-shell-v2"
const SHELL = ["/offline.html", "/icons/icon-192.png", "/icons/icon-512.png"]

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()))
})

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener("fetch", (event) => {
  const req = event.request
  // Page loads only: try the network, and if it's unreachable show the offline page.
  if (req.mode === "navigate") {
    event.respondWith(fetch(req).catch(() => caches.match("/offline.html")))
    return
  }
  // The shell's own icons may come from the cache; everything else goes to the network untouched.
  const url = new URL(req.url)
  if (url.origin === self.location.origin && SHELL.includes(url.pathname)) {
    event.respondWith(caches.match(req).then((hit) => hit || fetch(req)))
  }
})

// A notification from the server (harness/push.py): {title, body, url, tag}.
// The same tag as the open app's own notification replaces it, never doubles it.
self.addEventListener("push", (event) => {
  let msg = {}
  try { msg = event.data ? event.data.json() : {} } catch { msg = { body: event.data ? event.data.text() : "" } }
  event.waitUntil(self.registration.showNotification(msg.title || "Hangul", {
    body: msg.body || "",
    icon: "/icons/icon-192.png",
    badge: "/icons/icon-192.png",
    tag: msg.tag || undefined,
    data: { url: msg.url || "/" },
  }))
})

// A tap opens Hangul where the notification points, reusing an open window.
self.addEventListener("notificationclick", (event) => {
  event.notification.close()
  const target = new URL((event.notification.data && event.notification.data.url) || "/", self.location.origin)
  if (target.origin !== self.location.origin) return          // only ever our own pages
  event.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true })
    for (const w of wins) {
      if (new URL(w.url).origin === target.origin && "focus" in w) {
        await w.focus()
        if ("navigate" in w) await w.navigate(target.href).catch(() => null)
        return
      }
    }
    await self.clients.openWindow(target.href)
  })())
})
