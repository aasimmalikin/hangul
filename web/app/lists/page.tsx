"use client"

import { useCallback, useEffect, useState } from "react"
import { useSession } from "next-auth/react"
import { AppHeader } from "@/components/hangul/AppHeader"
import { SignInModal, type AuthMode } from "@/components/hangul/SignInModal"

/**
 * /lists — everything the assistant keeps for the user, in one place: their
 * to-do / shopping lists (tick, add, delete), upcoming reminders (cancel) and
 * notes (search, delete). The chat creates these ("add milk to my shopping
 * list"); this page is for looking and tidying up.
 */

type Item = { id: number; list_name: string; text: string; done: boolean }
type Reminder = { id: number; text: string; due_at: string; status: string }
type NoteRow = { id: number; text: string; created_at: string }
type FileRow = { name: string; size: number; modified: number; kind: string }

const FILE_ICON: Record<string, string> = {
  document: "file-text", slides: "presentation", spreadsheet: "file-spreadsheet", text: "file-text",
  image: "photo", audio: "microphone", file: "file",
}
const fileUrl = (n: string) => `/api/files/${encodeURIComponent(n)}`
const size = (n: number) => (n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`)

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/${path}`, { ...init, cache: "no-store", headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } })
  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try { detail = (await res.json()).detail ?? detail } catch {}
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

function Section({ title, hint, children, testId }: { title: string; hint?: string; children: React.ReactNode; testId?: string }) {
  return (
    <section className="h-surface" data-testid={testId} style={{ padding: "18px 20px", display: "flex", flexDirection: "column", gap: 10 }}>
      <div>
        <h2 className="h-display" style={{ fontSize: 18, margin: 0 }}>{title}</h2>
        {hint && <p className="h-muted" style={{ fontSize: 12, margin: "4px 0 0" }}>{hint}</p>}
      </div>
      {children}
    </section>
  )
}

export default function ListsPage() {
  const { status: authStatus } = useSession()
  const [signIn, setSignIn] = useState<{ open: boolean; mode: AuthMode }>({ open: false, mode: "signin" })
  const [gateDismissed, setGateDismissed] = useState(false)
  const signInOpen = signIn.open || (authStatus === "unauthenticated" && !gateDismissed)

  const [lists, setLists] = useState<Record<string, Item[]>>({})
  const [reminders, setReminders] = useState<Reminder[]>([])
  const [notes, setNotes] = useState<NoteRow[]>([])
  const [files, setFiles] = useState<FileRow[]>([])
  const [query, setQuery] = useState("")
  const [newItem, setNewItem] = useState("")
  const [newList, setNewList] = useState("To-do")
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      const [l, r, n, f] = await Promise.all([
        api<{ lists: Record<string, Item[]> }>("lists"),
        api<Reminder[]>("reminders?scope=open"),
        api<NoteRow[]>("notes"),
        api<FileRow[]>("files").catch(() => [] as FileRow[]),
      ])
      setLists(l.lists); setReminders(r); setNotes(n); setFiles(f); setError(null)
    } catch (e) { setError((e as Error).message) }
  }, [])

  useEffect(() => {
    if (authStatus !== "authenticated") return
    // Fetch-on-sign-in; state is set after the await (same pattern as /settings).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void reload()
  }, [authStatus, reload])

  const run = async (fn: () => Promise<unknown>) => {
    try { await fn(); await reload() } catch (e) { setError((e as Error).message) }
  }
  const searchNotes = async (q: string) => {
    setQuery(q)
    try { setNotes(await api<NoteRow[]>(`notes?q=${encodeURIComponent(q)}`)) } catch (e) { setError((e as Error).message) }
  }

  const names = Object.keys(lists)

  return (
    <main className="h-has-bottom-nav" style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <AppHeader onSignIn={() => setSignIn({ open: true, mode: "signin" })} onSignUp={() => setSignIn({ open: true, mode: "signup" })} />
      <SignInModal open={signInOpen} mode={signIn.mode} onClose={() => { setGateDismissed(true); setSignIn((s) => ({ ...s, open: false })) }} callbackUrl="/lists" reason="Sign in to see your lists." />

      <div style={{ width: "100%", maxWidth: 760, margin: "0 auto", padding: "8px 16px 40px", display: "flex", flexDirection: "column", gap: 16, boxSizing: "border-box" }}>
        <div>
          <h1 className="h-display" style={{ fontSize: 26, margin: "8px 0 4px" }}>My stuff</h1>
          <p className="h-muted" style={{ fontSize: 13, margin: 0 }}>
            Just tell the assistant — “add eggs to my shopping list”, “remind me to pay rent on the 1st at 9am”, “note: Wi-Fi password is on the router”. It all shows up here.
          </p>
        </div>
        {error && <div className="h-surface" style={{ padding: 12, fontSize: 13, color: "var(--err)" }} role="alert">{error}</div>}

        <Section title="Lists" testId="lists-section">
          <form style={{ display: "flex", gap: 8, flexWrap: "wrap" }}
            onSubmit={(e) => { e.preventDefault(); if (!newItem.trim()) return; void run(async () => { await api("lists", { method: "POST", body: JSON.stringify({ list: newList || "To-do", text: newItem }) }); setNewItem("") }) }}>
            <input className="h-input" style={{ flex: "2 1 200px" }} placeholder="Add an item…" value={newItem} onChange={(e) => setNewItem(e.target.value)} maxLength={500} aria-label="New item" />
            <input className="h-input" style={{ flex: "1 1 110px" }} placeholder="List" value={newList} onChange={(e) => setNewList(e.target.value)} maxLength={60} aria-label="List name" list="list-names" />
            <datalist id="list-names">{names.map((n) => <option key={n} value={n} />)}</datalist>
            <button className="h-btn-solid" type="submit">Add</button>
          </form>
          {names.length === 0 && <p className="h-muted" style={{ fontSize: 13, margin: 0 }}>No lists yet.</p>}
          {names.map((name) => (
            <div key={name} data-testid={`list-${name}`}>
              <div style={{ fontSize: 13, fontWeight: 500, margin: "6px 0" }}>{name}</div>
              {lists[name].map((it) => (
                <div key={it.id} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 14, padding: "3px 0" }}>
                  <input type="checkbox" checked={it.done} aria-label={`Done: ${it.text}`} style={{ width: 16, height: 16, accentColor: "var(--fg)" }}
                    onChange={() => void run(() => api(`lists/items/${it.id}`, { method: "PATCH", body: JSON.stringify({ done: !it.done }) }))} />
                  <span style={{ flex: 1, textDecoration: it.done ? "line-through" : undefined }}>{it.text}</span>
                  <button className="h-btn-ghost" aria-label={`Delete ${it.text}`} style={{ padding: "2px 6px" }}
                    onClick={() => void run(() => api(`lists/items/${it.id}`, { method: "DELETE" }))}>
                    <i className="ti ti-x" style={{ fontSize: 13 }} />
                  </button>
                </div>
              ))}
            </div>
          ))}
        </Section>

        <Section title="Reminders" hint="They pop up in the bell at the top and arrive by email." testId="reminders-section">
          {reminders.length === 0 && <p className="h-muted" style={{ fontSize: 13, margin: 0 }}>No reminders. Ask: “remind me to call mom at 7pm”.</p>}
          {reminders.map((r) => (
            <div key={r.id} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 14 }}>
              <span className="h-muted" style={{ fontSize: 12, minWidth: 140 }}>
                {new Date(r.due_at).toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}
              </span>
              <span style={{ flex: 1 }}>{r.text}{r.status === "sent" && <span className="h-muted" style={{ fontSize: 11 }}> · due</span>}</span>
              <button className="h-btn-ghost" style={{ fontSize: 12, padding: "3px 8px" }}
                onClick={() => void run(() => r.status === "sent" ? api(`reminders/${r.id}/done`, { method: "POST" }) : api(`reminders/${r.id}`, { method: "DELETE" }))}>
                {r.status === "sent" ? "Done" : "Cancel"}
              </button>
            </div>
          ))}
        </Section>

        <Section title="Notes" testId="notes-section">
          <input className="h-input" placeholder="Search notes…" value={query} onChange={(e) => void searchNotes(e.target.value)} aria-label="Search notes" />
          {notes.length === 0 && <p className="h-muted" style={{ fontSize: 13, margin: 0 }}>{query ? "No matching notes." : "No notes yet."}</p>}
          {notes.map((n) => (
            <div key={n.id} style={{ display: "flex", gap: 10, fontSize: 14 }}>
              <div style={{ flex: 1, whiteSpace: "pre-wrap" }}>
                {n.text}
                <div className="h-muted" style={{ fontSize: 11 }}>{new Date(n.created_at).toLocaleDateString()}</div>
              </div>
              <button className="h-btn-ghost" aria-label="Delete note" style={{ padding: "2px 6px", alignSelf: "flex-start" }}
                onClick={() => void run(() => api(`notes/${n.id}`, { method: "DELETE" }))}>
                <i className="ti ti-trash" style={{ fontSize: 13 }} />
              </button>
            </div>
          ))}
        </Section>
        <Section title="Files" hint="Everything you uploaded and everything Hangul made for you: documents, charts, images and voice notes." testId="files-section">
          {files.length === 0 && <p className="h-muted" style={{ fontSize: 13, margin: 0 }}>No files yet. Try “make a PDF of my notes” or add a file with +.</p>}
          {files.map((f) => (
            <div key={f.name} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 14 }} data-testid={`file-${f.name}`}>
              {f.kind === "image"
                // eslint-disable-next-line @next/next/no-img-element -- a private, per-user file behind the BFF
                ? <img src={fileUrl(f.name)} alt="" style={{ width: 36, height: 36, objectFit: "cover", borderRadius: 6 }} />
                : <i className={`ti ti-${FILE_ICON[f.kind] ?? "file"}`} style={{ fontSize: 20, width: 36, textAlign: "center" }} />}
              <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.name}</span>
              <span className="h-muted" style={{ fontSize: 12 }}>{size(f.size)} · {new Date(f.modified * 1000).toLocaleDateString()}</span>
              <a className="h-btn-ghost" href={fileUrl(f.name)} download={f.name} aria-label={`Download ${f.name}`} style={{ padding: "2px 6px" }}>
                <i className="ti ti-download" style={{ fontSize: 14 }} />
              </a>
            </div>
          ))}
        </Section>
      </div>
    </main>
  )
}
