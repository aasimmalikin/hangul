"use client"

import { useCallback, useEffect, useState, useSyncExternalStore } from "react"

function subscribeOnline(cb: () => void) {
  window.addEventListener("online", cb)
  window.addEventListener("offline", cb)
  return () => {
    window.removeEventListener("online", cb)
    window.removeEventListener("offline", cb)
  }
}

export type Connectivity = {
  /** Browser thinks it has a network. */
  online: boolean
  /** Our backend answered /api/health recently. null = not checked yet. */
  backendOk: boolean | null
  /** Re-check now (after an error, on retry). */
  recheck: () => Promise<boolean>
}

const POLL_OK_MS = 60_000
const POLL_DOWN_MS = 10_000

/**
 * Two signals the UI needs to explain a failure honestly: is the *browser*
 * offline (nothing we can do), or is our *backend* down (we are retrying)?
 * Re-checks on `online`, on tab focus, and when the page is restored from the
 * back/forward cache — the moments a stale answer would mislead.
 */
export function useConnectivity(): Connectivity {
  // navigator.onLine is the browser's own signal; read it through
  // useSyncExternalStore so SSR renders "online" and the client corrects it
  // without a setState-in-effect.
  const online = useSyncExternalStore(subscribeOnline, () => navigator.onLine, () => true)
  const [backendOk, setBackendOk] = useState<boolean | null>(null)

  const recheck = useCallback(async () => {
    try {
      const res = await fetch("/api/health", { cache: "no-store", signal: AbortSignal.timeout(5_000) })
      const ok = res.ok
      setBackendOk(ok)
      return ok
    } catch {
      setBackendOk(false)
      return false
    }
  }, [])

  useEffect(() => {
    const up = () => void recheck()
    const onShow = (e: PageTransitionEvent) => { if (e.persisted) void recheck() }
    const onVis = () => { if (document.visibilityState === "visible") void recheck() }
    window.addEventListener("online", up)
    window.addEventListener("pageshow", onShow)
    document.addEventListener("visibilitychange", onVis)
    // First check after mount (deferred: the state update lands in its own tick).
    const first = setTimeout(() => void recheck(), 0)
    return () => {
      clearTimeout(first)
      window.removeEventListener("online", up)
      window.removeEventListener("pageshow", onShow)
      document.removeEventListener("visibilitychange", onVis)
    }
  }, [recheck])

  // Poll slowly while healthy, quickly while down so recovery shows fast.
  useEffect(() => {
    if (!online) return
    const id = setInterval(() => void recheck(), backendOk === false ? POLL_DOWN_MS : POLL_OK_MS)
    return () => clearInterval(id)
  }, [online, backendOk, recheck])

  return { online, backendOk, recheck }
}
