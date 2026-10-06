"use client"

import { useCallback, useEffect, useState } from "react"

/**
 * The Kept tab's drawer: undated things Hangul holds for the user -- lists
 * (tick, add, delete), notes (search, delete), what it remembers (forget) and
 * files (download). Everything dated (reminders, scheduled tasks, actions) is
 * on the Day line above it. This was the whole of the old "My stuff" page.
 */

type Item = { id: number; list_name: string; text: string; done: boolean }
type NoteRow = { id: number; text: string; created_at: string }
type MemoryRow = { id: number; content: string; created_at: string }
type FileRow = { name: string; size: number; modified: number; kind: string }
export type HoldingSection = "lists" | "notes" | "memories" | "files"

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

function Section({ id, title, hint, children, testId }: { id: HoldingSection; title: string; hint?: string; children: React.ReactNode; testId?: string }) {
  return (
    <section id={`holding-${id}`} className="h-surface" data-testid={testId} style={{ padding: "18px 20px", display: "flex", flexDirection: "column", gap: 10, scrollMarginTop: 80 }}>
      <div>
        <h3 className="h-display" style={{ fontSize: 18, margin: 0, fontWeight: 400 }}>{title}</h3>
        {hint && <p className="h-muted" style={{ fontSize: 12, margin: "4px 0 0" }}>{hint}</p>}
      </div>
      {children}
    </section>
  )
}

export function KeptHolding({ onChange }: { onChange?: () => void }) {
  const [lists, setLists] = useState<Record<string, Item[]>>({})
  const [notes, setNotes] = useState<NoteRow[]>([])
  const [memories, setMemories] = useState<MemoryRow[]>([])
  const [files, setFiles] = useState<FileRow[]>([])
  const [query, setQuery] = useState("")
  const [newItem, setNewItem] = useState("")
  const [newList, setNewList] = useState("To-do")
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      const [l, n, m, f] = await Promise.all([
        api<{ lists: Record<string, Item[]> }>("lists"),
        api<NoteRow[]>("notes"),
        api<MemoryRow[]>("memory").catch(() => [] as MemoryRow[]),
        api<FileRow[]>("files").catch(() => [] as FileRow[]),
      ])
      setLists(l.lists); setNotes(n); setMemories(m); setFiles(f); setError(null)
    } catch (e) { setError((e as Error).message) }
  }, [])

  // Fetch on open; state is set after the await (same pattern as /settings).
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void reload() }, [reload])

  const run = async (fn: () => Promise<unknown>) => {
    try { await fn(); await reload(); onChange?.() } catch (e) { setError((e as Error).message) }
  }
  const searchNotes = async (q: string) => {
    setQuery(q)
    try { setNotes(await api<NoteRow[]>(`notes?q=${encodeURIComponent(q)}`)) } catch (e) { setError((e as Error).message) }
  }

  const names = Object.keys(lists)

  return (
    <div className="h-kept-holding">
      {error && <div className="h-surface" style={{ padding: 12, fontSize: 13, color: "var(--err)" }} role="alert">{error}</div>}

      <Section id="lists" title="Lists" testId="lists-section">
        <form style={{ display: "flex", gap: 8, flexWrap: "wrap" }}
          onSubmit={(e) => { e.preventDefault(); if (!newItem.trim()) return; void run(async () => { await api("lists", { method: "POST", body: JSON.stringify({ list: newList || "To-do", text: newItem }) }); setNewItem("") }) }}>
          <input className="h-input" style={{ flex: "2 1 200px" }} placeholder="Add an item…" value={newItem} onChange={(e) => setNewItem(e.target.value)} maxLength={500} aria-label="New item" />
          <input className="h-input" style={{ flex: "1 1 110px" }} placeholder="List" value={newList} onChange={(e) => setNewList(e.target.value)} maxLength={60} aria-label="List name" list="list-names" />
          <datalist id="list-names">{names.map((n) => <option key={n} value={n} />)}</datalist>
          <button className="h-btn-solid" type="submit">Add</button>
        </form>
        {names.length === 0 && <p className="h-muted" style={{ fontSize: 13, margin: 0 }}>No lists yet. Try “add milk and eggs to my shopping list”.</p>}
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

      <Section id="notes" title="Notes" testId="notes-section">
        <input className="h-input" placeholder="Search notes…" value={query} onChange={(e) => void searchNotes(e.target.value)} aria-label="Search notes" />
        {notes.length === 0 && <p className="h-muted" style={{ fontSize: 13, margin: 0 }}>{query ? "No matching notes." : "No notes yet. Try “note: the Wi-Fi password is on the router”."}</p>}
        {notes.map((n) => (
          <div key={n.id} style={{ display: "flex", gap: 10, fontSize: 14 }}>
            <div style={{ flex: 1, whiteSpace: "pre-wrap", minWidth: 0 }}>
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

      <Section id="memories" title="Remembered" hint="Things you told Hangul about yourself. It uses them in every answer." testId="memories-section">
        {memories.length === 0 && <p className="h-muted" style={{ fontSize: 13, margin: 0 }}>Nothing yet. Try “remember that I&apos;m vegetarian”.</p>}
        {memories.map((m) => (
          <div key={m.id} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 14 }}>
            <span style={{ flex: 1, minWidth: 0 }}>{m.content}</span>
            <button className="h-btn-ghost" style={{ fontSize: 12, padding: "3px 8px" }} aria-label={`Forget ${m.content}`}
              onClick={() => void run(() => api(`memory/${m.id}`, { method: "DELETE" }))}>Forget</button>
          </div>
        ))}
      </Section>

      <Section id="files" title="Files" hint="Everything you uploaded and everything Hangul made for you." testId="files-section">
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
  )
}
