"use client"

import { useEffect, useRef, useState } from "react"
import { Recorder, transcribe, voiceSupported, VoiceFailure } from "@/lib/voice"
import type { ApiFailure } from "@/lib/apiError"

/**
 * Tap to talk: tap once to start, tap again to stop. The words are turned
 * into text and handed to `onText` (the composer sends them). Hidden on
 * browsers without a microphone API.
 */
export function MicButton({ onText, onFailure, disabled }: {
  onText: (text: string) => void
  onFailure?: (f: ApiFailure) => void
  disabled?: boolean
}) {
  const [state, setState] = useState<"idle" | "recording" | "working">("idle")
  const [secs, setSecs] = useState(0)
  const [supported, setSupported] = useState(false)
  const rec = useRef<Recorder | null>(null)

  // eslint-disable-next-line react-hooks/set-state-in-effect -- browser capability, known only after mount
  useEffect(() => { setSupported(voiceSupported()) }, [])
  useEffect(() => {
    if (state !== "recording") return
    const t = setInterval(() => setSecs((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [state])
  useEffect(() => () => rec.current?.cancel(), [])

  if (!supported) return null

  const start = async () => {
    const r = (rec.current = new Recorder())
    setSecs(0)
    let recording
    try {
      setState("recording")
      recording = await r.start({ maxMs: 120_000 })
    } catch {
      setState("idle")
      onFailure?.({ code: "mic_blocked", detail: "Allow microphone access in your browser to talk to Hangul." })
      return
    }
    if (!recording || recording.seconds < 0.4) { setState("idle"); return }
    setState("working")
    try {
      const text = await transcribe(recording)
      if (text) onText(text)
      else onFailure?.({ code: "no_speech", detail: "I didn't catch anything — try again a little closer to the mic." })
    } catch (e) {
      onFailure?.(e instanceof VoiceFailure ? e.failure : { code: "network", detail: "Couldn't reach the server for voice." })
    } finally {
      setState("idle")
    }
  }

  const label = state === "recording" ? "Stop and send" : state === "working" ? "Listening…" : "Talk"
  return (
    <button type="button" className="h-icon-btn" aria-label={label} title={label} data-testid="mic-button"
      data-state={state} disabled={disabled || state === "working"}
      onClick={() => (state === "recording" ? rec.current?.stop() : void start())}
      style={{ borderRadius: 999, gap: 4, width: state === "recording" ? "auto" : undefined, padding: state === "recording" ? "0 10px" : undefined,
        background: state === "recording" ? "var(--err)" : undefined, color: state === "recording" ? "var(--solid-fg)" : undefined }}>
      <i className={`ti ${state === "working" ? "ti-loader-2 animate-spin" : state === "recording" ? "ti-player-stop-filled" : "ti-microphone"}`} style={{ fontSize: 16 }} />
      {state === "recording" && <span style={{ fontSize: 12, fontVariantNumeric: "tabular-nums" }}>{Math.floor(secs / 60)}:{String(secs % 60).padStart(2, "0")}</span>}
    </button>
  )
}
