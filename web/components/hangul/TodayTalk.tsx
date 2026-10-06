"use client"

import { useEffect, useMemo, useRef, useState } from "react"

/**
 * Hangul talks first: the top of Today is a few short messages to the user,
 * built from GET /api/today with templates (no model call), each with one-tap
 * replies. Chips either act in place -- the morning check-in (POST
 * /api/today/checkin), keeping or forgetting a memory (DELETE /api/memory/<id>)
 * -- or hand a request to the chat through `onAsk`, exactly like typing it, so
 * every approval and plan rule still applies. The cards below keep the detail.
 *
 * The messages "type in" one after another the first time Today is opened in
 * a tab each day; after that (and with reduced motion) they are simply there.
 */
export type TalkBrief = {
  name: string
  events: Array<{ summary: string; start: string; all_day?: boolean }> | null
  weather: { daily?: Array<{ rain_chance: number | null }> } | null
  leave_by?: { summary: string; minutes?: number | null; leave_at?: string; late?: boolean } | null
  replies?: Array<{ from: string; subject: string; waiting_days: number }> | null
  birthdays?: Array<{ name: string; date: string; in_days: number; turns?: number }> | null
  checkin?: { mood: string | null; reply: string | null; streak: number; week: boolean[] } | null
  memory?: { id: number; content: string } | null
}

type Chip = { label: string; testId?: string; run: () => void | Promise<void> }
type Msg = { id: string; text: string; me?: boolean; chips?: Chip[] }

const MOODS: Array<[string, string]> = [["great", "Great"], ["ok", "Okay"], ["tired", "Tired"], ["busy", "Swamped"]]
const time = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
const sender = (from: string) => (from.match(/^\s*"?([^"<]*?)"?\s*</)?.[1] || from.replace(/@.*/, "")).trim()
const when = (b: { date: string; in_days: number }) =>
  b.in_days === 0 ? "today" : b.in_days === 1 ? "tomorrow" : `on ${new Date(`${b.date}T12:00:00`).toLocaleDateString(undefined, { weekday: "long" })}`

const ANSWERED_KEY = () => `hangul:checkin-answered:${new Date().toDateString()}`
const FELT: Record<string, string> = { great: "feeling great", ok: "okay", tired: "tired", busy: "swamped" }

/** Ask the living stag to look up and glint (LivingStag listens for this). */
export const cheerStag = () => window.dispatchEvent(new Event("hangul:stag-cheer"))

export function TodayTalk({ brief, onAsk }: { brief: TalkBrief; onAsk: (text: string) => void }) {
  const [extra, setExtra] = useState<Msg[]>([])
  const [hidden, setHidden] = useState<Set<string>>(new Set())
  const [checkin, setCheckin] = useState(brief.checkin ?? null)
  // The check-in is asked every time Hangul is opened (a new tab or app launch), not once a day:
  // only an answer given in this tab counts as answered. Today's mood on the server is the latest
  // answer, so a new one simply replaces it. (Today only renders client-side, after /today loads.)
  const [answeredHere, setAnsweredHere] = useState(() => {
    try { return sessionStorage.getItem(ANSWERED_KEY()) === "1" } catch { return false }
  })
  const [shown, setShown] = useState(0)
  const endRef = useRef<HTMLDivElement>(null)

  const say = (text: string, me = false) => setExtra((xs) => [...xs, { id: `x${xs.length}-${Date.now()}`, text, me }])
  const answer = (id: string, label: string, reply?: string) => {
    setHidden((h) => new Set(h).add(id))
    say(label, true)
    if (reply) setTimeout(() => say(reply), 350)
  }

  const base = useMemo<Msg[]>(() => {
    const out: Msg[] = []
    const events = brief.events?.filter((e) => !e.all_day) ?? null
    const rain = brief.weather?.daily?.[0]?.rain_chance
    if (events) {
      const day = events.length === 0 ? "Nothing on your calendar today."
        : events.length === 1 ? `One thing on your calendar today: ${events[0].summary} at ${time(events[0].start)}.`
        : `${events.length} things on your calendar today, starting with ${events[0].summary} at ${time(events[0].start)}.`
      out.push({ id: "day", text: rain != null && rain >= 40 ? `${day} Rain is likely, so take an umbrella.` : day })
    }
    const lb = brief.leave_by
    if (lb && lb.minutes != null && lb.leave_at) {
      out.push({ id: "leave", text: lb.late ? `You should leave now for ${lb.summary} (${lb.minutes} min drive).`
        : `Leave by ${time(lb.leave_at)} for ${lb.summary}. It's a ${lb.minutes} min drive.` })
    }
    const r = brief.replies?.[0]
    if (r) {
      const who = sender(r.from)
      out.push({ id: "reply", text: `${who} has been waiting ${r.waiting_days} day${r.waiting_days === 1 ? "" : "s"} for your reply about “${r.subject}”. Want me to draft one?`,
        chips: [
          { label: "Draft a reply", testId: "talk-draft", run: () => onAsk(`Draft a reply to ${who}'s email "${r.subject}".`) },
          { label: "Later", run: () => answer("reply", "Later", "Okay, I'll bring it up again later.") },
        ] })
    }
    const b = brief.birthdays?.[0]
    if (b) {
      out.push({ id: "bday", text: `${b.name} ${b.turns ? `turns ${b.turns}` : "has a birthday"} ${when(b)}.`,
        chips: [{ label: "Draft a wish", run: () => onAsk(`Help me write a warm birthday message for ${b.name}.`) }] })
    }
    const m = brief.memory
    if (m) {
      out.push({ id: "memory", text: `You told me: “${m.content}”. Still right?`,
        chips: [
          { label: "Still right", run: () => { answer("memory", "Still right", "Good. I'll keep it in mind."); cheerStag() } },
          { label: "Forget it", testId: "talk-memory-forget", run: async () => {
            const res = await fetch(`/api/memory/${m.id}`, { method: "DELETE" }).catch(() => null)
            answer("memory", "Forget it", res?.ok ? "Forgotten. I won't use that any more." : "I couldn't forget that just now. Try again from the You page.")
          } },
        ] })
    }
    return out
    // `answer`/`onAsk` are stable enough for a list built once per brief
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brief])

  const earlier = checkin?.mood ? FELT[checkin.mood] : null
  const checkinMsgs: Msg[] = answeredHere && checkin?.mood
    ? [{ id: "mood-done", text: `${checkin.reply ?? ""}${checkin.streak >= 2 ? ` That's ${checkin.streak} mornings in a row together.` : ""}`.trim() }]
    : [{ id: "mood", text: earlier ? `How are you feeling now? Earlier today you said you were ${earlier}.` : "How are you feeling today?",
        chips: MOODS.map(([mood, label]) => ({
          label, testId: `talk-mood-${mood}`,
          run: async () => {
            const res = await fetch("/api/today/checkin", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mood }) }).catch(() => null)
            if (res?.ok) {
              setCheckin(await res.json())
              setAnsweredHere(true)
              try { sessionStorage.setItem(ANSWERED_KEY(), "1") } catch { /* private mode: asked again on reload */ }
              cheerStag()
            } else say("I couldn't save that just now, but thanks for telling me.")
          },
        })) }]
  // the check-in comes second: after the day's shape, before the details
  const at = base[0]?.id === "day" ? 1 : 0
  const all = [...base.slice(0, at), ...checkinMsgs, ...base.slice(at)].filter((m) => !hidden.has(m.id))
  const visible = [...all.slice(0, shown), ...(shown >= all.length ? extra : [])]

  // type the messages in one by one, once per tab per day
  useEffect(() => {
    const key = `hangul:talk-seen:${new Date().toDateString()}`
    let instant = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    try { instant = instant || sessionStorage.getItem(key) === "1"; sessionStorage.setItem(key, "1") } catch { /* private mode */ }
    // eslint-disable-next-line react-hooks/set-state-in-effect -- motion preference and sessionStorage are only known after mount
    if (instant) { setShown(Number.MAX_SAFE_INTEGER); return }
    let n = 0
    const t = window.setInterval(() => { n += 1; setShown(n); if (n >= 8) window.clearInterval(t) }, 650)
    return () => window.clearInterval(t)
  }, [])
  useEffect(() => { endRef.current?.scrollIntoView({ block: "nearest" }) }, [visible.length])

  if (all.length === 0) return null
  const typing = shown < all.length
  return (
    <div className="h-talk" data-testid="today-talk" aria-live="polite">
      {visible.map((m, i) => (
        <div key={m.id} className="h-talk-row">
          <div className={m.me ? "h-talk-msg is-me" : "h-talk-msg"} data-testid="talk-msg">{m.text}</div>
          {m.chips && !m.me && (i === visible.length - 1 || !typing) && (
            <div className="h-talk-chips">
              {m.chips.map((c, k) => (
                <button key={c.label} type="button" className={k === 0 ? "h-btn-solid h-talk-chip" : "h-chip"} data-testid={c.testId ?? "talk-chip"}
                  onClick={() => void c.run()}>{c.label}</button>
              ))}
            </div>
          )}
        </div>
      ))}
      {typing && <div className="h-talk-typing" aria-label="Hangul is typing"><i /><i /><i /></div>}
      <div ref={endRef} />
    </div>
  )
}
