"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { matchOption, Recorder, sharedSpeaker, transcribe, VoiceFailure, yesOrNo } from "@/lib/voice"
import type { ApiFailure } from "@/lib/apiError"

/**
 * Hands-free voice mode: a full-screen conversation. It listens, sends what
 * the user said as a normal chat message, reads the answer aloud, and listens
 * again. An approval is asked out loud ("…say yes or no") and a clarifying
 * question reads its options. Tap the orb to interrupt or to talk again.
 *
 * It drives the chat page through callbacks, so everything (tools, approvals,
 * history, billing) is exactly the text chat's.
 */

export type VoicePause =
  | { kind: "approval"; key: string; summary: string }
  | { kind: "choice"; key: string; question: string; options: string[] }

type Phase = "idle" | "listening" | "transcribing" | "thinking" | "speaking"

const PHASE_TEXT: Record<Phase, string> = {
  idle: "Tap to talk",
  listening: "Listening…",
  transcribing: "Got it…",
  thinking: "Thinking…",
  speaking: "Speaking — tap to interrupt",
}

export function VoiceMode({ open, onClose, send, streaming, reply, pause, decide, choose, onFailure }: {
  open: boolean
  onClose: () => void
  send: (text: string) => void
  streaming: boolean
  /** The latest assistant answer: id + what to say. */
  reply: { id: string; text: string } | null
  /** An unanswered approval / question at the end of the thread. */
  pause: VoicePause | null
  /** Approve or reject the pending action; resolves with what to say next. */
  decide: (yes: boolean) => Promise<string | null>
  choose: (option: string) => Promise<string | null>
  onFailure: (f: ApiFailure) => void
}) {
  const [phase, setPhase] = useState<Phase>("idle")
  const [heard, setHeard] = useState("")
  const [level, setLevel] = useState(0)
  const rec = useRef<Recorder | null>(null)
  const waitingFor = useRef<{ after: string | null } | null>(null)   // sent; waiting for a new reply
  const pending = useRef<VoicePause | null>(null)                  // asked out loud; awaiting yes/no / option
  const alive = useRef(false)
  // listen() re-arms itself after each turn; it calls the latest version via this ref
  const again = useRef<() => void>(() => {})

  const fail = useCallback((e: unknown) => {
    if (e instanceof VoiceFailure) onFailure(e.failure)
    setPhase("idle")
  }, [onFailure])

  const say = useCallback(async (text: string) => {
    if (!alive.current || !text.trim()) return
    setPhase("speaking")
    await sharedSpeaker().speak(text)
  }, [])

  const listen = useCallback(async () => {
    if (!alive.current) return
    sharedSpeaker().stop()
    const r = (rec.current = new Recorder())
    setPhase("listening")
    setLevel(0)
    let recording
    try {
      recording = await r.start({ silenceMs: 1200, noSpeechMs: 9000, maxMs: 90_000, onLevel: setLevel })
    } catch {
      onFailure({ code: "mic_blocked", detail: "Allow microphone access in your browser to use voice mode." })
      setPhase("idle")
      return
    }
    if (!alive.current) return
    if (!recording) { setPhase("idle"); return }      // nothing said: wait for a tap
    setPhase("transcribing")
    let text = ""
    try { text = await transcribe(recording) } catch (e) { fail(e); return }
    if (!alive.current) return
    if (!text) { await say("Sorry, I didn't catch that."); return again.current() }
    setHeard(text)

    // answering a question the assistant asked out loud
    const p = pending.current
    if (p) {
      let next: string | null = null
      if (p.kind === "approval") {
        const yn = yesOrNo(text)
        if (!yn) { await say("Please say yes or no."); return again.current() }
        pending.current = null
        setPhase("thinking")
        next = await decide(yn === "yes")
      } else {
        const pick = matchOption(text, p.options)
        if (!pick) { await say(`Which one? ${p.options.join(", or ")}.`); return again.current() }
        pending.current = null
        setPhase("thinking")
        next = await choose(pick)
      }
      if (next === null) {                    // the run paused again: the effect below asks it
        waitingFor.current = { after: reply?.id ?? null }
        return
      }
      try { await say(next) } catch (e) { return fail(e) }
      return again.current()
    }

    waitingFor.current = { after: reply?.id ?? null }
    setPhase("thinking")
    send(text)
  }, [decide, choose, fail, onFailure, reply, say, send])
  useEffect(() => { again.current = () => void listen() }, [listen])

  // a new answer (or a pause) arrived for what we sent: say it, then listen again
  useEffect(() => {
    const w = waitingFor.current
    if (!open || !w || streaming) return
    if (pause && pending.current?.key !== pause.key) {
      waitingFor.current = null
      pending.current = pause
      const prompt = pause.kind === "approval"
        ? `I need your OK first: ${pause.summary}. Should I go ahead? Say yes or no.`
        : `${pause.question} Your options are: ${pause.options.join(", or ")}.`
      void (async () => { try { await say(prompt) } catch (e) { return fail(e) } ; again.current() })()
      return
    }
    if (reply && reply.id !== w.after && reply.text) {
      waitingFor.current = null
      void (async () => { try { await say(reply.text) } catch (e) { return fail(e) } ; again.current() })()
    }
  }, [open, streaming, reply, pause, say, fail])

  // open -> start listening; close -> stop everything
  useEffect(() => {
    if (!open) return
    alive.current = true
    // Entering voice mode turns the microphone on (an external device); the
    // phase shown is the mic's state, so it is set as part of starting it.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void listen()
    return () => {
      alive.current = false
      waitingFor.current = null
      pending.current = null
      rec.current?.cancel()
      sharedSpeaker().stop()
      setPhase("idle")
    }
    // listen is intentionally not a dependency: re-running would restart the mic on every render
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  if (!open) return null

  const tapOrb = () => {
    if (phase === "listening") rec.current?.stop()           // done talking
    else if (phase === "speaking" || phase === "idle") void listen()
  }
  const scale = phase === "listening" ? 1 + Math.min(level * 6, 0.45) : phase === "speaking" ? 1.08 : 1

  return (
    <div role="dialog" aria-label="Voice mode" data-testid="voice-mode" data-phase={phase}
      style={{ position: "fixed", inset: 0, zIndex: 60, background: "var(--bg)", display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center", gap: 28, padding: 24 }}>
      <button className="h-btn-ghost" onClick={onClose} aria-label="Exit voice mode" data-testid="voice-exit"
        style={{ position: "absolute", top: 16, right: 16, gap: 6 }}>
        <i className="ti ti-x" style={{ fontSize: 16 }} /> Exit
      </button>

      {/* The button stays still (an easy target); the ring behind it pulses with the voice. */}
      <div style={{ position: "relative", width: 160, height: 160 }}>
        <div aria-hidden style={{ position: "absolute", inset: 0, borderRadius: "50%", background: "var(--surface-hover)",
          transform: `scale(${scale + 0.12})`, transition: "transform 120ms ease-out", opacity: phase === "idle" ? 0 : 1 }} />
        <button type="button" onClick={tapOrb} aria-label={PHASE_TEXT[phase]} data-testid="voice-orb"
          style={{ position: "absolute", inset: 0, borderRadius: "50%", border: 0, cursor: "pointer",
            background: phase === "listening" ? "var(--fg)" : "var(--surface-solid)",
            color: phase === "listening" ? "var(--bg)" : "var(--fg)", transition: "background 200ms",
            display: "grid", placeItems: "center", boxShadow: "0 0 0 1px var(--surface-border)" }}>
          <i className={`ti ${phase === "thinking" || phase === "transcribing" ? "ti-loader-2 animate-spin"
            : phase === "speaking" ? "ti-volume" : "ti-microphone"}`} style={{ fontSize: 44 }} />
        </button>
      </div>

      <div style={{ textAlign: "center", maxWidth: 480 }}>
        <p className="h-display" style={{ fontSize: 20, margin: 0 }} data-testid="voice-status">{PHASE_TEXT[phase]}</p>
        {heard && <p className="h-muted" style={{ fontSize: 14, margin: "10px 0 0" }}>“{heard}”</p>}
        {phase === "idle" && (
          <p className="h-muted" style={{ fontSize: 12, margin: "10px 0 0" }}>
            Try “what&apos;s on my shopping list?” or “remind me to call mom at 7”.
          </p>
        )}
      </div>
    </div>
  )
}
