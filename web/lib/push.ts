/**
 * Notifications on this device (Web Push). The browser subscribes through its
 * own push service with the server's public key, and the subscription goes to
 * /api/push/subscribe; the server then notifies this device even when Hangul
 * is closed. Needs the service worker, which is registered in production only.
 */

export type PushState =
  | "unsupported"     // this browser can't (or the service worker isn't running, e.g. dev)
  | "needs-install"   // iPhone/iPad: only an app added to the Home Screen can get notifications
  | "off"             // server not set up
  | "blocked"         // the user said no in the browser; only browser settings can undo it
  | "available"       // can be turned on
  | "on"

type Status = { enabled: boolean; public_key: string | null; devices: number; this_device: boolean }

const isIos = () => typeof navigator !== "undefined" && /iphone|ipad|ipod/i.test(navigator.userAgent)
const standalone = () =>
  window.matchMedia("(display-mode: standalone)").matches || (navigator as Navigator & { standalone?: boolean }).standalone === true

async function registration(): Promise<ServiceWorkerRegistration | null> {
  if (!("serviceWorker" in navigator)) return null
  // getRegistration, not .ready: .ready never settles when no worker is registered (dev)
  return (await navigator.serviceWorker.getRegistration("/").catch(() => undefined)) ?? null
}

async function current(): Promise<PushSubscription | null> {
  const reg = await registration()
  return reg?.pushManager ? reg.pushManager.getSubscription().catch(() => null) : null
}

function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const pad = "=".repeat((4 - (base64url.length % 4)) % 4)
  const raw = atob((base64url + pad).replace(/-/g, "+").replace(/_/g, "/"))
  const out = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i)
  return out
}

async function status(endpoint?: string): Promise<Status | null> {
  const q = endpoint ? `?endpoint=${encodeURIComponent(endpoint)}` : ""
  const res = await fetch(`/api/push${q}`, { cache: "no-store" }).catch(() => null)
  return res && res.ok ? res.json() : null
}

export async function pushState(): Promise<PushState> {
  if (typeof window === "undefined" || !("Notification" in window) || !("PushManager" in window)) {
    return isIos() && !standalone() ? "needs-install" : "unsupported"
  }
  const reg = await registration()
  if (!reg) return "unsupported"
  const sub = await current()
  const s = await status(sub?.endpoint)
  if (!s?.enabled) return "off"
  if (Notification.permission === "denied") return "blocked"
  if (sub && s.this_device && Notification.permission === "granted") return "on"
  if (sub && Notification.permission === "granted") {
    // subscribed in the browser but the server forgot it (signed in as someone else, or it expired): re-send
    return (await save(sub)) ? "on" : "available"
  }
  return "available"
}

async function save(sub: PushSubscription): Promise<boolean> {
  const res = await fetch("/api/push/subscribe", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(sub.toJSON()),
  }).catch(() => null)
  return !!res && res.ok
}

/** Ask permission (must follow a tap), subscribe, and register this device. */
export async function enablePush(): Promise<PushState> {
  const reg = await registration()
  if (!reg?.pushManager) return "unsupported"
  const s = await status()
  if (!s?.enabled || !s.public_key) return "off"
  const permission = await Notification.requestPermission()
  if (permission !== "granted") return permission === "denied" ? "blocked" : "available"
  let sub = await current()
  if (sub) {
    // made with an older server key? start over
    const old = sub.options?.applicationServerKey
    const want = keyBytes(s.public_key)
    if (old && !sameBytes(new Uint8Array(old), want)) { await sub.unsubscribe().catch(() => null); sub = null }
  }
  sub ??= await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(s.public_key) }).catch(() => null)
  if (!sub) return "available"
  return (await save(sub)) ? "on" : "available"
}

export async function disablePush(): Promise<PushState> {
  const sub = await current()
  if (sub) {
    await fetch("/api/push/unsubscribe", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ endpoint: sub.endpoint }),
    }).catch(() => null)
    await sub.unsubscribe().catch(() => null)
  }
  return "available"
}

export async function testPush(): Promise<number> {
  const res = await fetch("/api/push/test", { method: "POST" }).catch(() => null)
  return res && res.ok ? ((await res.json()).sent as number) : 0
}

/**
 * A notification from the open page. Android Chrome refuses `new Notification()`
 * and only allows it through the service worker, so use that when there is one.
 */
export async function showLocal(title: string, options: NotificationOptions & { data?: unknown }) {
  if (typeof Notification === "undefined" || Notification.permission !== "granted") return
  const reg = await registration()
  if (reg) { await reg.showNotification(title, { icon: "/icons/icon-192.png", badge: "/icons/icon-192.png", ...options }).catch(() => null); return }
  try { new Notification(title, options) } catch { /* unsupported */ }
}

function sameBytes(a: Uint8Array, b: Uint8Array) {
  return a.length === b.length && a.every((x, i) => x === b[i])
}
