"use client"

import { useEffect, useState } from "react"

type InstallEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: string }> }

/**
 * "Put Hangul on your home screen": an Install button where the browser
 * supports it (Chrome / Edge / Android), and the Share → Add to Home Screen
 * hint on iPhone Safari. Hidden once installed or dismissed.
 */
export function InstallTip() {
  const [evt, setEvt] = useState<InstallEvent | null>(null)
  const [ios, setIos] = useState(false)
  const [hidden, setHidden] = useState(true)

  useEffect(() => {
    let dismissed = false
    try { dismissed = localStorage.getItem("hangul:install-tip") === "dismissed" } catch { /* private mode */ }
    const standalone = window.matchMedia("(display-mode: standalone)").matches || (navigator as Navigator & { standalone?: boolean }).standalone
    if (dismissed || standalone) return
    const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent) && /safari/i.test(navigator.userAgent) && !/crios|fxios/i.test(navigator.userAgent)
    // eslint-disable-next-line react-hooks/set-state-in-effect -- browser capability, known only after mount
    if (isIos) { setIos(true); setHidden(false) }
    const onPrompt = (e: Event) => { e.preventDefault(); setEvt(e as InstallEvent); setHidden(false) }
    window.addEventListener("beforeinstallprompt", onPrompt)
    return () => window.removeEventListener("beforeinstallprompt", onPrompt)
  }, [])

  if (hidden || (!evt && !ios)) return null
  const dismiss = () => { setHidden(true); try { localStorage.setItem("hangul:install-tip", "dismissed") } catch { /* ignore */ } }

  return (
    <div className="h-surface" data-testid="install-tip"
      style={{ padding: "10px 12px", borderRadius: 14, display: "flex", alignItems: "center", gap: 10, fontSize: 13, width: "100%", boxSizing: "border-box" }}>
      <i className="ti ti-device-mobile" style={{ fontSize: 18 }} />
      <span style={{ flex: 1 }}>
        {ios ? <>Put Hangul on your home screen: tap <i className="ti ti-share-2" /> <b>Share</b>, then <b>Add to Home Screen</b>.</>
             : <>Put Hangul on your home screen — it opens like an app.</>}
      </span>
      {evt && (
        <button className="h-btn-solid" style={{ padding: "4px 12px" }}
          onClick={async () => { await evt.prompt(); await evt.userChoice.catch(() => null); setHidden(true) }}>Install</button>
      )}
      <button className="h-btn-ghost" aria-label="Dismiss" onClick={dismiss} style={{ padding: "2px 6px" }}><i className="ti ti-x" style={{ fontSize: 14 }} /></button>
    </div>
  )
}
