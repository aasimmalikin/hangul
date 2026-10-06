"use client"

import { useEffect, useRef, useState } from "react"
import { Recorder, transcribe, voiceSupported, VoiceFailure } from "@/lib/voice"
import type { ApiFailure } from "@/lib/apiError"

/**
 * Tap to talk. The first tap asks the browser for the microphone; the timer
 * starts only once access is granted and recording has really begun. It sends
 * by itself once the user stops talking; Stop sends straight away and × throws
 * the recording away.
 * The words are turned into text and handed to `onText` (the composer sends
 * them). Hidden on browsers without a microphone API.
 */
export function MicButton({ onText, onFailure, disabled }: {
  onText: (text: string) => void
  onFailure?: (f: ApiFailure) => void
  disabled?: boolean
}) {
  const [state, setState] = useState<"idle" | "asking" | "recording" | "working">("idle")
  const [secs, setSecs] = useState(0)
  const [supported, setSupported] = useState(false)
  const rec = useRef<Recorder | null>(null)
  const discarded = useRef(false)

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
    discarded.current = false
    setSecs(0)
    setState("asking")                       // the browser may be showing its permission prompt
    let recording
    try {
      recording = await r.start({ silenceMs: 1500, noSpeechMs: 10_000, maxMs: 120_000, onStart: () => setState("recording") })
    } catch {
      setState("idle")
      onFailure?.({ code: "mic_blocked", detail: "Allow microphone access in your browser to talk to Hangul." })
      return
    }
    if (!recording) {                        // discarded, or nothing was said
      if (!discarded.current) onFailure?.({ code: "no_speech", detail: "I didn't hear anything — tap the mic and try again." })
      setState("idle")
      return
    }
    if (recording.seconds < 0.4) { setState("idle"); return }
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

  const discard = () => { discarded.current = true; rec.current?.cancel(); setState("idle") }
  const onClick = () => {
    if (state === "recording") rec.current?.stop()
    else if (state === "asking") discard()
    else void start()
  }

  const label = state === "recording" ? "Stop and send" : state === "asking" ? "Waiting for microphone access — tap to cancel"
    : state === "working" ? "Listening…" : "Talk"
  const pill = state === "recording" || state === "asking"
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      {state === "recording" && (
        <button type="button" className="h-icon-btn" aria-label="Discard recording" title="Discard recording"
          data-testid="mic-cancel" onClick={discard} style={{ borderRadius: 999 }}>
          <i className="ti ti-x" style={{ fontSize: 15 }} />
        </button>
      )}
      <button type="button" className="h-icon-btn" aria-label={label} title={label} data-testid="mic-button"
        data-state={state} disabled={disabled || state === "working"} onClick={onClick}
        style={{ borderRadius: 999, gap: 6, width: pill ? "auto" : undefined, padding: pill ? "0 10px" : undefined,
          background: state === "recording" ? "var(--err)" : undefined, color: state === "recording" ? "var(--solid-fg)" : undefined }}>
        <i className={`ti ${state === "working" || state === "asking" ? "ti-loader-2 animate-spin" : state === "recording" ? "ti-player-stop-filled" : "ti-microphone"}`} style={{ fontSize: 16 }} />
        {state === "asking" && <span style={{ fontSize: 12 }}>Allow mic…</span>}
        {state === "recording" && (
          <span style={{ fontSize: 12, fontVariantNumeric: "tabular-nums" }}>
            {Math.floor(secs / 60)}:{String(secs % 60).padStart(2, "0")} · Stop
          </span>
        )}
      </button>
    </span>
  )
}
