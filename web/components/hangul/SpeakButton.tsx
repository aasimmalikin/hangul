"use client"

import { useEffect, useState } from "react"
import { sharedSpeaker, VoiceFailure } from "@/lib/voice"
import type { ApiFailure } from "@/lib/apiError"

/** 🔊 under an answer: read it aloud; tap again to stop. */
export function SpeakButton({ text, onFailure }: { text: string; onFailure?: (f: ApiFailure) => void }) {
  const [playing, setPlaying] = useState(false)
  useEffect(() => () => { if (playing) sharedSpeaker().stop() }, [playing])
  if (!text.trim()) return null
  const toggle = async () => {
    const sp = sharedSpeaker()
    if (playing) { sp.stop(); setPlaying(false); return }
    setPlaying(true)
    try {
      await sp.speak(text)
    } catch (e) {
      if (e instanceof VoiceFailure) onFailure?.(e.failure)
    } finally {
      setPlaying(false)
    }
  }
  return (
    <button type="button" className="h-btn-ghost" onClick={() => void toggle()} data-testid="speak-button"
      aria-label={playing ? "Stop reading" : "Read aloud"} title={playing ? "Stop reading" : "Read aloud"}
      style={{ padding: "2px 6px", fontSize: 12, gap: 4, color: "var(--muted)" }}>
      <i className={`ti ${playing ? "ti-player-stop" : "ti-volume"}`} style={{ fontSize: 14 }} />
      {playing ? "Stop" : "Listen"}
    </button>
  )
}
