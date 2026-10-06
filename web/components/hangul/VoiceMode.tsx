"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { matchOption, Recorder, sharedSpeaker, transcribe, VoiceFailure, yesOrNo, type VoiceMeter } from "@/lib/voice"
import { SpeakingStag } from "@/components/hangul/SpeakingStag"
import type { ApiFailure } from "@/lib/apiError"

/**
 * Hands-free voice mode: a full-screen conversation. It listens, sends what
 * the user said as a normal chat message, reads the answer aloud, and listens
 * again -- no button: a turn ends when the user stops talking. An approval
 * is asked out loud ("…say yes or no") and a clarifying question reads its
 * options. After about 40 s of silence the mic turns off until the orb is
 * tapped; tapping it while Hangul speaks interrupts.
 *
 * It drives the chat page through callbacks, so everything (tools, approvals,
 * history, billing) is exactly the text chat's.
 */

export type VoicePause =
  | { kind: "approval"; key: string; summary: string }
  | { kind: "choice"; key: string; question: string; options: string[] }

/** Silent listens (≈10 s each) before the mic is switched off to wait for a tap. */
const QUIET_ROUNDS = 4

type Phase = "idle" | "asking" | "listening" | "transcribing" | "thinking" | "speaking"

const PHASE_TEXT: Record<Phase, string> = {
  idle: "Tap to talk",
  asking: "Allow microphone access to start",
  listening: "Listening… just talk, I'll answer when you stop",
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
  const micLevel = useRef(0)                                       // read each frame by the stag
  const rec = useRef<Recorder | null>(null)
  const waitingFor = useRef<{ after: string | null } | null>(null)   // sent; waiting for a new reply
  const pending = useRef<VoicePause | null>(null)                  // asked out loud; awaiting yes/no / option
  const alive = useRef(false)
  const quietRounds = useRef(0)                                    // listens in a row with no speech
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
    setPhase("asking")                       // the browser may be showing its permission prompt
    micLevel.current = 0
    let recording
    try {
      recording = await r.start({ silenceMs: 1200, noSpeechMs: 10_000, maxMs: 90_000, onLevel: (l) => { micLevel.current = l },
        onStart: () => setPhase("listening") })
    } catch {
      onFailure({ code: "mic_blocked", detail: "Allow microphone access in your browser to use voice mode." })
      setPhase("idle")
      return
    }
    if (!alive.current) return
    if (!recording) {
      // nothing said: keep listening for a while, then turn the mic off and wait for a tap
      if (++quietRounds.current < QUIET_ROUNDS) return again.current()
      quietRounds.current = 0
      setPhase("idle")
      return
    }
    quietRounds.current = 0
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
  // what moves the stag: Hangul's voice while speaking, the user's while listening
  const meter = (): VoiceMeter | null => {
    if (phase === "speaking") return sharedSpeaker().meter()
    const l = Math.min(1, micLevel.current * 8)
    return { level: l, bands: [l, l * 0.8, l * 0.6, l * 0.4, l * 0.3] }
  }

  return (
    <div role="dialog" aria-label="Voice mode" data-testid="voice-mode" data-phase={phase}
      style={{ position: "fixed", inset: 0, zIndex: 60, background: "var(--bg)", display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center", gap: 28, padding: 24 }}>
      <button className="h-btn-ghost" onClick={onClose} aria-label="Exit voice mode" data-testid="voice-exit"
        style={{ position: "absolute", top: 16, right: 16, gap: 6 }}>
        <i className="ti ti-x" style={{ fontSize: 16 }} /> Exit
      </button>

      {/* Hangul itself is the button: tap to talk, to finish, or to interrupt. */}
      <button type="button" onClick={tapOrb} aria-label={PHASE_TEXT[phase]} data-testid="voice-orb"
        style={{ border: 0, padding: 0, background: "none", cursor: "pointer", borderRadius: "50%", WebkitTapHighlightColor: "transparent" }}>
        <SpeakingStag phase={phase} meter={meter} size={220} />
      </button>

      <div style={{ textAlign: "center", maxWidth: 480 }}>
        <p className="h-display" style={{ fontSize: 20, margin: 0 }} data-testid="voice-status">{PHASE_TEXT[phase]}</p>
        {heard && <p className="h-muted" style={{ fontSize: 14, margin: "10px 0 0" }}>“{heard}”</p>}
        {phase === "listening" && (
          <button type="button" className="h-btn-solid" onClick={() => rec.current?.stop()} data-testid="voice-stop"
            style={{ marginTop: 16, gap: 6, background: "var(--err)" }}>
            <i className="ti ti-player-stop-filled" style={{ fontSize: 13 }} /> Stop
          </button>
        )}
        {phase === "idle" && (
          <p className="h-muted" style={{ fontSize: 12, margin: "10px 0 0" }}>
            Try “what&apos;s on my shopping list?” or “remind me to call mom at 7”.
          </p>
        )}
      </div>
    </div>
  )
}
