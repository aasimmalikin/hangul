"use client"

import { useCallback, useEffect, useState } from "react"

/**
 * Connectors the user can switch on for a conversation ("+ → Connectors").
 * The list comes from the backend (`/api/connectors`); the selection lives in
 * this tab's sessionStorage so the landing page and /chat share it and a new
 * tab starts clean, like the chat thread itself. What is on goes up with
 * every message as `connectors`; the backend validates the keys.
 */
export type ConnectorInfo = {
  key: string; label: string; description: string; kind: "builtin" | "mcp"; icon: string
  /** Needs the user's own account session (e.g. Google OAuth) before it can be switched on. */
  per_user?: boolean
  /** Which connect flow the UI offers ("google"). */
  auth?: string | null
  servers?: string[]
  /** OAuth product whose scopes it needs ("gmail", "calendar"…); checked against `Integrations.google.products`. */
  product?: string | null
  /** Connectors sharing a group are listed together under that heading ("Google Workspace"). */
  group?: string | null
  /** Needs Google's restricted scopes (Gmail, Drive); hidden when `Integrations.google.restricted` is false. */
  restricted?: boolean
}

/** The old all-in-one Google key, replaced by one connector per product. */
const LEGACY_EXPANSIONS: Record<string, string[]> = { google: ["gmail", "calendar", "drive", "docs"] }

/** Swap retired keys for their replacements (deduped, order kept). */
export function normalizeConnectors(keys: string[]): string[] {
  const out: string[] = []
  for (const k of keys) for (const x of LEGACY_EXPANSIONS[k] ?? [k]) if (!out.includes(x)) out.push(x)
  return out
}

/** Every offered Google Workspace scope (no Docs or Meet: google_oauth.UNOFFERED_PRODUCTS); the fallback
 *  when the backend didn't say which this account may ask for. */
export const GOOGLE_WORKSPACE_SCOPES = [
  "openid", "email", "profile",
  "https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.compose",
  "https://www.googleapis.com/auth/calendar",
  "https://www.googleapis.com/auth/drive.readonly", "https://www.googleapis.com/auth/drive.file",
  "https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive.metadata.readonly",
  "https://www.googleapis.com/auth/contacts.readonly", "https://www.googleapis.com/auth/contacts.other.readonly",
].join(" ")

export type Integrations = {
  /** `scopes`: what Connect Google should ask for. `restricted`: may this account use Gmail and Drive
   *  (false until Google's yearly security assessment is done, except for invited testers). */
  google: { connected: boolean; products: string[]; scopes: string[]; restricted?: boolean }
  /** GitHub / Notion / Slack tokens saved in the vault */
  apps?: Partial<Record<"github" | "notion" | "slack", boolean>>
}

/** The `scope` string for Connect Google: only what this account may use (no Gmail or Drive unless invited). */
export function googleScopes(i: Integrations | null): string {
  const scopes = i?.google.scopes ?? []
  return scopes.length ? ["openid", "email", "profile", ...scopes].join(" ") : GOOGLE_WORKSPACE_SCOPES
}

/** False for Gmail and Drive when this account isn't on the restricted list. */
export function offeredTo(c: ConnectorInfo, i: Integrations | null): boolean {
  return !c.restricted || i?.google.restricted !== false
}

/** What the signed-in user has connected; null when signed out or unreachable. */
export async function loadIntegrations(): Promise<Integrations | null> {
  try {
    const r = await fetch("/api/integrations", { cache: "no-store", signal: AbortSignal.timeout(8_000) })
    return r.ok ? ((await r.json()) as Integrations) : null
  } catch { return null }
}

export const CONNECTORS_KEY = "hangul:connectors"
const KEY_RE = /^[a-z0-9_-]{1,32}$/

export function readConnectors(): string[] {
  try {
    const raw = sessionStorage.getItem(CONNECTORS_KEY)
    const list = raw ? JSON.parse(raw) : []
    return Array.isArray(list) ? normalizeConnectors(list.filter((k): k is string => typeof k === "string" && KEY_RE.test(k))) : []
  } catch { return [] }
}

export function writeConnectors(keys: string[]) {
  try { sessionStorage.setItem(CONNECTORS_KEY, JSON.stringify(keys)) } catch { /* private mode / quota */ }
}

let cached: ConnectorInfo[] | null = null
let inflight: Promise<ConnectorInfo[]> | null = null

/** The catalogue, fetched once per page load; empty when the backend is unreachable. */
export function loadAvailableConnectors(): Promise<ConnectorInfo[]> {
  if (cached) return Promise.resolve(cached)
  if (!inflight) {
    inflight = fetch("/api/connectors", { cache: "no-store", signal: AbortSignal.timeout(8_000) })
      .then(async (r) => (r.ok ? ((await r.json()) as ConnectorInfo[]) : []))
      .catch(() => [] as ConnectorInfo[])
      .then((list) => { cached = list; inflight = null; return list })
  }
  return inflight
}

/** Selected connector keys for this tab, plus a setter that persists them. */
export function useConnectorSelection(initial?: string[]): [string[], (next: string[]) => void] {
  const [keys, setKeys] = useState<string[]>(initial ?? [])
  useEffect(() => {
    // Read after mount so the server and client render the same (empty) list.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (initial === undefined) setKeys(readConnectors())
  }, [initial])
  const set = useCallback((next: string[]) => { setKeys(next); writeConnectors(next) }, [])
  return [keys, set]
}

/** Deep-research mode chosen on the landing page, carried to /chat in this tab. */
export const RESEARCH_KEY = "hangul:research"

export function readResearchMode(): boolean {
  try { return sessionStorage.getItem(RESEARCH_KEY) === "1" } catch { return false }
}

export function writeResearchMode(on: boolean) {
  try { sessionStorage.setItem(RESEARCH_KEY, on ? "1" : "0") } catch { /* private mode */ }
}

export function useResearchMode(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(false)
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOn(readResearchMode())
  }, [])
  const set = useCallback((v: boolean) => { setOn(v); writeResearchMode(v) }, [])
  return [on, set]
}
