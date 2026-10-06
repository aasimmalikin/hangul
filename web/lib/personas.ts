"use client"

import { useEffect, useState } from "react"

/**
 * Who the user is (user_settings.persona; the backend list is
 * db/settings.PERSONAS). Picked in onboarding or /settings. Here it decides the
 * starter prompts on the home screen and in an empty chat; the backend uses it
 * for the system prompt and the plan /billing recommends.
 */
export type Persona = "founder" | "developer" | "student" | "professional" | "personal"

export const PERSONAS: Array<{ key: Persona; label: string; icon: string }> = [
  { key: "founder", label: "Founder", icon: "rocket" },
  { key: "developer", label: "Developer", icon: "code" },
  { key: "student", label: "Student", icon: "school" },
  { key: "professional", label: "Professional", icon: "briefcase" },
  { key: "personal", label: "Personal use", icon: "home" },
]

/** A one-tap prompt: `send` asks right away, otherwise it fills the box to finish. */
export type Prompt = { label: string; text: string; send: boolean; icon: string }

const DEFAULT_HOME: Prompt[] = [
  { label: "Plan my day", text: "Plan my day: what's on my calendar, what's due, and what should I focus on?", send: true, icon: "sun" },
  { label: "Remind me…", text: "Remind me to ", send: false, icon: "alarm" },
  { label: "Search my documents", text: "Search my documents", send: true, icon: "file-search" },
  { label: "Make a document", text: "Make a PDF of ", send: false, icon: "file-type-pdf" },
]

const HOME: Record<Persona, Prompt[]> = {
  founder: [
    DEFAULT_HOME[0],
    { label: "Who needs a reply?", text: "Which emails need a reply from me? Draft short replies for the top three.", send: true, icon: "mail-forward" },
    { label: "Prep my next meeting", text: "Prep me for my next meeting: who's in it, what we last discussed by email, and what I need to decide.", send: true, icon: "users" },
    DEFAULT_HOME[1],
  ],
  developer: [
    DEFAULT_HOME[0],
    { label: "My GitHub work", text: "What's on my plate on GitHub: pull requests to review and issues assigned to me?", send: true, icon: "brand-github" },
    { label: "Explain an error", text: "Explain this error and how to fix it: ", send: false, icon: "bug" },
    DEFAULT_HOME[1],
  ],
  student: [
    { label: "Plan my study day", text: "Plan my day around my classes and deadlines: what's due, and what should I study first?", send: true, icon: "calendar-time" },
    { label: "Find papers", text: "Find recent papers on ", send: false, icon: "books" },
    { label: "Make study notes", text: "Make study notes as a PDF on ", send: false, icon: "notes" },
    DEFAULT_HOME[1],
  ],
  professional: [
    DEFAULT_HOME[0],
    { label: "Summarise my inbox", text: "Summarise my important unread emails and tell me which need a reply", send: true, icon: "mail" },
    { label: "When am I free?", text: "When am I free this week for a one-hour meeting?", send: true, icon: "calendar-search" },
    { label: "Draft an email", text: "Draft an email to ", send: false, icon: "pencil" },
  ],
  personal: DEFAULT_HOME,
}

/** Chips at the top of an empty chat, ahead of the everyday ones. */
const CHAT: Record<Persona, Array<Omit<Prompt, "send">>> = {
  founder: [{ icon: "mail-forward", label: "Who needs a reply?", text: "Which emails need a reply from me today?" }],
  developer: [{ icon: "bug", label: "Explain an error", text: "Explain this error and how to fix it: " }],
  student: [{ icon: "books", label: "Find papers", text: "Find recent papers on " }],
  professional: [{ icon: "pencil", label: "Draft an email", text: "Draft an email to " }],
  personal: [],
}

export const homePrompts = (p: Persona | null): Prompt[] => (p ? HOME[p] : DEFAULT_HOME)
export const chatStarters = (p: Persona | null) => (p ? CHAT[p] : [])

let cached: Persona | null | undefined

/** The signed-in user's persona (null until known or not chosen); one /api/settings read per page load. */
export function usePersona(enabled = true): Persona | null {
  const [persona, setPersona] = useState<Persona | null>(cached ?? null)
  useEffect(() => {
    if (!enabled) return
    let alive = true
    if (cached === undefined) {
      void fetch("/api/settings", { cache: "no-store" })
        .then((r) => (r.ok ? r.json() : null))
        .then((s: { persona?: string } | null) => {
          const p = PERSONAS.some((x) => x.key === s?.persona) ? (s!.persona as Persona) : null
          cached = p
          if (alive) setPersona(p)
        })
        .catch(() => {})
    }
    // onboarding / settings just changed it
    const changed = (e: Event) => { cached = (e as CustomEvent<Persona | null>).detail; setPersona(cached ?? null) }
    window.addEventListener("hangul:persona", changed)
    return () => { alive = false; window.removeEventListener("hangul:persona", changed) }
  }, [enabled])
  return persona
}

/** Tell open pages the persona changed (after saving it). */
export function announcePersona(p: Persona | null) {
  cached = p
  window.dispatchEvent(new CustomEvent("hangul:persona", { detail: p }))
}
