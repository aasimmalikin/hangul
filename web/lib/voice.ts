"use client"

/**
 * Browser side of voice: record the mic, send it for transcription, and speak
 * answers back. Speech is a front end on the normal chat — a transcript is
 * sent as an ordinary message — so every tool, approval and limit applies.
 *
 *   Recorder   MediaRecorder + a level meter; optional auto-stop after the
 *              user stops talking (hands-free mode)
 *   transcribe POST /api/voice/transcribe -> text
 *   Speaker    splits an answer into sentence chunks and plays them in order,
 *              fetching the next chunk while the current one plays, so the
 *              first words come quickly even for a long answer
 */

import { failureFromResponse, type ApiFailure } from "@/lib/apiError"

export class VoiceFailure extends Error {
  constructor(public readonly failure: ApiFailure) { super(failure.detail) }
}

export const voiceSupported = () =>
  typeof window !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined"

function pickMime(): string {
  const options = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"]
  return options.find((m) => typeof MediaRecorder.isTypeSupported === "function" && MediaRecorder.isTypeSupported(m)) ?? ""
}

const extFor = (mime: string) => (mime.includes("mp4") ? "m4a" : mime.includes("ogg") ? "ogg" : "webm")

export type Recording = { blob: Blob; seconds: number; ext: string }

export type RecorderOptions = {
  /** Hands-free: stop by itself once the user has spoken and then been quiet this long. */
  silenceMs?: number
  /** Give up (resolve empty) if no speech starts within this long. */
  noSpeechMs?: number
  maxMs?: number
  onLevel?: (level: number) => void
  /** Fires once the browser has granted the mic and recording has really begun
   *  (not while its permission prompt is still open). */
  onStart?: () => void
}

// What counts as talking adapts to the room: the noise floor is tracked while
// nobody speaks, and speech is a level well above it (never below MIN_SPEECH,
// so a silent room doesn't make breathing count as words).
const MIN_SPEECH = 0.02
const SPEECH_OVER_FLOOR = 2.5

export class Recorder {
  private stream?: MediaStream
  private rec?: MediaRecorder
  private chunks: Blob[] = []
  private ctx?: AudioContext
  private timer?: number
  private started = 0
  private heardSpeech = false
  private lastLoud = 0
  private done?: (r: Recording | null) => void
  private mime = ""
  private aborted = false
  private stoppedByUser = false

  get recording() { return this.rec?.state === "recording" }

  /** Starts recording; the promise settles when stop() is called or auto-stop fires. */
  async start(opts: RecorderOptions = {}): Promise<Recording | null> {
    this.aborted = false
    this.stoppedByUser = false
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
    // cancelled while the permission prompt was open: release the mic at once
    if (this.aborted) { stream.getTracks().forEach((t) => t.stop()); return null }
    this.stream = stream
    this.mime = pickMime()
    this.rec = new MediaRecorder(this.stream, this.mime ? { mimeType: this.mime } : undefined)
    this.chunks = []
    this.rec.ondataavailable = (e) => { if (e.data.size) this.chunks.push(e.data) }
    this.started = this.lastLoud = performance.now()
    this.heardSpeech = false

    const result = new Promise<Recording | null>((resolve) => { this.done = resolve })
    this.rec.onstop = () => {
      const seconds = (performance.now() - this.started) / 1000
      const type = this.rec?.mimeType || this.mime || "audio/webm"
      const blob = new Blob(this.chunks, { type })
      this.cleanup()
      // a hands-free recording with no speech is dropped, unless the user chose to stop it
      const keep = this.heardSpeech || !opts.silenceMs || this.stoppedByUser
      this.done?.(keep ? { blob, seconds, ext: extFor(type) } : null)
    }
    this.rec.start(250)
    opts.onStart?.()

    // level meter (+ silence detection in hands-free mode)
    try {
      this.ctx = new AudioContext()
      const analyser = this.ctx.createAnalyser()
      analyser.fftSize = 1024
      this.ctx.createMediaStreamSource(this.stream).connect(analyser)
      const buf = new Float32Array(analyser.fftSize)
      let floor = 0.01
      let loudFor = 0                        // ms above the threshold so far
      let last = performance.now()
      const tick = () => {
        if (!this.recording) return
        analyser.getFloatTimeDomainData(buf)
        let sum = 0
        for (const v of buf) sum += v * v
        const level = Math.sqrt(sum / buf.length)
        opts.onLevel?.(level)
        const now = performance.now()
        const threshold = Math.max(MIN_SPEECH, floor * SPEECH_OVER_FLOOR)
        if (level > threshold) {
          loudFor += now - last
          // a click or a bump isn't speech: it takes a little loudness in all first
          if (loudFor >= 100) this.heardSpeech = true
          this.lastLoud = now
        } else {
          // follow the room: fall quickly to quiet, rise slowly with steady noise
          floor = level < floor ? floor * 0.8 + level * 0.2 : floor * 0.98 + level * 0.02
        }
        last = now
        if (opts.silenceMs && this.heardSpeech && now - this.lastLoud > opts.silenceMs) return this.finish()
        if (opts.noSpeechMs && !this.heardSpeech && now - this.started > opts.noSpeechMs) return this.finish()
        if (opts.maxMs && now - this.started > opts.maxMs) return this.finish()
        this.timer = window.setTimeout(tick, 60)
      }
      tick()
    } catch { /* no meter: manual stop still works */ }
    return result
  }

  /** The user's Stop: keeps what was recorded. */
  stop() {
    this.stoppedByUser = true
    this.finish()
  }

  private finish() {
    if (this.rec && this.rec.state !== "inactive") this.rec.stop()
    else this.cleanup()
  }

  /** Stop without producing a recording (the start() promise settles with null). */
  cancel() {
    this.aborted = true
    const settle = this.done
    this.done = undefined
    this.finish()
    settle?.(null)
  }

  private cleanup() {
    if (this.timer) window.clearTimeout(this.timer)
    this.stream?.getTracks().forEach((t) => t.stop())
    void this.ctx?.close().catch(() => {})
    this.ctx = undefined
  }
}

export async function transcribe(rec: Recording, signal?: AbortSignal): Promise<string> {
  const form = new FormData()
  form.append("file", rec.blob, `speech.${rec.ext}`)
  form.append("seconds", String(Math.round(rec.seconds)))
  const res = await fetch("/api/voice/transcribe", { method: "POST", body: form, signal })
  if (!res.ok) throw new VoiceFailure(await failureFromResponse(res))
  return String((await res.json()).text ?? "").trim()
}

/** Sentence-sized chunks; the first is kept short so speech starts fast. */
export function speechChunks(text: string): string[] {
  // a sentence ends at . ! ? … followed by a space -- so "notes.txt" or "3.5" stay whole
  const sentences = text.replace(/\s+/g, " ").trim().split(/(?<=[.!?…]["')\]]*)\s+/)
  const out: string[] = []
  let cur = ""
  for (const s of sentences.map((x) => x.trim()).filter(Boolean)) {
    const limit = out.length === 0 ? 160 : 600
    if (cur && (cur + " " + s).length > limit) { out.push(cur); cur = s } else cur = cur ? `${cur} ${s}` : s
  }
  if (cur) out.push(cur)
  return out
}

/** How loud the voice is right now: `level` 0..1 and five bands, low to high pitch. */
export type VoiceMeter = { level: number; bands: number[] }
const BAND_HZ = [80, 250, 500, 1000, 2000, 4000]      // edges of the five voice bands

/** Plays answers aloud, one at a time; a new speak() interrupts the current one. */
export class Speaker {
  private audio?: HTMLAudioElement
  private abort?: AbortController
  private session = 0
  private ctx?: AudioContext
  private analyser?: AnalyserNode
  private wave?: Float32Array<ArrayBuffer>
  private freq?: Uint8Array<ArrayBuffer>
  private unroute?: () => void
  onState?: (speaking: boolean) => void

  get speaking() { return !!this.abort }

  /**
   * The voice being played, for the speaking animation. null while speaking
   * when the browser gives no meter (the animation then fakes one); silence
   * when nothing is playing.
   */
  meter(): VoiceMeter | null {
    const a = this.audio
    if (!this.speaking || !a || a.paused || a.ended) return { level: 0, bands: [0, 0, 0, 0, 0] }
    if (!this.analyser || !this.wave || !this.freq || !this.ctx || this.ctx.state !== "running") return null
    this.analyser.getFloatTimeDomainData(this.wave)
    let sum = 0
    for (const v of this.wave) sum += v * v
    const level = Math.min(1, Math.sqrt(sum / this.wave.length) * 4)
    this.analyser.getByteFrequencyData(this.freq)
    const hzPerBin = this.ctx.sampleRate / this.analyser.fftSize
    const bands = BAND_HZ.slice(0, -1).map((lo, i) => {
      const from = Math.max(1, Math.floor(lo / hzPerBin)), to = Math.max(from + 1, Math.ceil(BAND_HZ[i + 1] / hzPerBin))
      let b = 0
      for (let k = from; k < to && k < this.freq!.length; k++) b += this.freq![k]
      return Math.min(1, (b / (to - from) / 255) * 1.6)
    })
    return { level, bands }
  }

  /** Starts Web Audio for the meter. Only used once it is really running: an
   *  element routed through a suspended context would play silently. */
  private async warmUp() {
    try {
      this.ctx ??= new AudioContext()
      if (this.ctx.state !== "running") {
        await Promise.race([this.ctx.resume(), new Promise((r) => setTimeout(r, 300))])
      }
      if (!this.analyser && this.ctx.state === "running") {
        this.analyser = this.ctx.createAnalyser()
        this.analyser.fftSize = 1024
        this.analyser.smoothingTimeConstant = 0.6
        this.analyser.connect(this.ctx.destination)
        this.wave = new Float32Array(this.analyser.fftSize)
        this.freq = new Uint8Array(this.analyser.frequencyBinCount)
      }
    } catch { /* no Web Audio: play without a meter */ }
  }

  private route(a: HTMLAudioElement): () => void {
    if (!this.ctx || !this.analyser || this.ctx.state !== "running") return () => {}
    try {
      const src = this.ctx.createMediaElementSource(a)
      src.connect(this.analyser)
      return () => { try { src.disconnect() } catch { /* already gone */ } }
    } catch { return () => {} }
  }

  stop() {
    this.session++
    this.abort?.abort()
    this.abort = undefined
    if (this.audio) { this.audio.pause(); this.audio.src = "" }
    this.unroute?.()
    this.unroute = undefined
    this.onState?.(false)
  }

  /** Resolves when everything was said (or it was stopped). Rejects on a billing refusal. */
  async speak(text: string): Promise<void> {
    this.stop()
    const session = ++this.session
    const abort = (this.abort = new AbortController())
    this.onState?.(true)
    const chunks = speechChunks(text)
    const warm = this.warmUp()
    const fetchChunk = async (t: string): Promise<string | null> => {
      const res = await fetch("/api/voice/speak", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: t }), signal: abort.signal,
      })
      if (res.status === 402) throw new VoiceFailure(await failureFromResponse(res))
      if (!res.ok) return null
      return URL.createObjectURL(await res.blob())
    }
    try {
      let next = chunks.length ? fetchChunk(chunks[0]) : null
      await warm
      for (let i = 0; i < chunks.length && session === this.session; i++) {
        const url = await next
        next = i + 1 < chunks.length ? fetchChunk(chunks[i + 1]) : null   // prefetch while this one plays
        if (!url || session !== this.session) continue
        await new Promise<void>((resolve) => {
          const a = (this.audio = new Audio(url))
          const unroute = (this.unroute = this.route(a))
          a.onended = a.onerror = () => { unroute(); URL.revokeObjectURL(url); resolve() }
          a.play().catch(() => resolve())          // autoplay blocked / undecodable: skip
        })
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") throw e
    } finally {
      if (session === this.session) { this.abort = undefined; this.onState?.(false) }
    }
  }
}

/** One speaker for the page, so starting one answer stops any other. */
let shared: Speaker | null = null
export const sharedSpeaker = () => (shared ??= new Speaker())

/** "yes" / "no" / null from a spoken reply to an approval question. */
export function yesOrNo(text: string): "yes" | "no" | null {
  const t = text.toLowerCase()
  if (/\b(no|nope|don'?t|do not|cancel|stop|reject|never|wait)\b/.test(t)) return "no"
  if (/\b(yes|yeah|yep|sure|ok(ay)?|go ahead|do it|approve|send it|confirm|please do|haan)\b/.test(t)) return "yes"
  return null
}

/** The option a spoken reply picks: by number ("the second one") or by words. */
export function matchOption(text: string, options: string[]): string | null {
  const t = text.toLowerCase()
  const ordinals = ["first", "second", "third", "fourth", "fifth"]
  for (let i = 0; i < options.length; i++) {
    if (new RegExp(`\\b(${ordinals[i]}|option ${i + 1}|number ${i + 1})\\b`).test(t)) return options[i]
  }
  let best: string | null = null
  let score = 0
  for (const o of options) {
    const words = o.toLowerCase().split(/\W+/).filter((w) => w.length > 2)
    const hit = words.filter((w) => t.includes(w)).length / Math.max(1, words.length)
    if (hit > score) { score = hit; best = o }
  }
  return score >= 0.5 ? best : null
}
