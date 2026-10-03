/*
 * Hangul's service worker: just enough to install and to show a friendly
 * offline page. Deliberately does NOT cache pages or /api responses -- those
 * are private and must always be fresh -- only the offline page and icons.
 */
const CACHE = "hangul-shell-v1"
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
