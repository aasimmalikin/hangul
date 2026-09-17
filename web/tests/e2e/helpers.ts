import { encode } from "next-auth/jwt"
import { expect, type BrowserContext, type Page } from "@playwright/test"

export const BACKEND = "http://127.0.0.1:8765"
const AUTH_SECRET = "e2e-auth-secret-e2e-auth-secret-e2e"

export type TestUser = { id: string; name: string; email: string }
export const alice: TestUser = { id: "101", name: "Alice Example", email: "alice@example.com" }
export const bob: TestUser = { id: "202", name: "Bob Example", email: "bob@example.com" }

let seq = 0
/** A user id nobody else in the run uses, so per-user limits and storage don't bleed between spec files. */
export function freshUser(label: string): TestUser {
  const id = String(1000 + Date.now() % 100000 + seq++)
  return { id, name: `${label} ${id}`, email: `${label.toLowerCase()}-${id}@example.com` }
}

/**
 * Mint a real Auth.js JWT session cookie, exactly as the app would after a
 * Google sign-in, so the BFF's `auth()` sees a genuine session.
 */
export async function signInAs(context: BrowserContext, user: TestUser, baseURL: string) {
  const name = "authjs.session-token"
  const value = await encode({
    token: { sub: user.id, name: user.name, email: user.email },
    secret: AUTH_SECRET,
    salt: name,
    maxAge: 3600,
  })
  const { hostname } = new URL(baseURL)
  await context.addCookies([{ name, value, domain: hostname, path: "/", httpOnly: true, sameSite: "Lax" }])
}

export async function signOut(context: BrowserContext) {
  await context.clearCookies()
}

export async function backend(path: string, body?: unknown) {
  const res = await fetch(`${BACKEND}${path}`, body ? { method: "POST", body: JSON.stringify(body) } : {})
  return res.json()
}
export const resetBackend = () => backend("/__reset")
/** Plant a conversation for `user` in the fake backend, optionally dated (ISO). */
export const seedChat = (user: TestUser, title: string, opts: { updated_at?: string; summary?: string } = {}) =>
  backend("/__episode", { user: user.id, title, ...opts })
export const backendState = () => backend("/__state") as Promise<{
  asks: { user: string; question: string; history: number; docs_only: boolean }[]
  executed: Record<string, number>
  uploads: { user: string; filename: string }[]
  memory: Record<string, { id: number; content: string; active: boolean }[]>
  episodes: Record<string, { id: number; thread_id: string; title: string; summary: string; active: boolean }[]>
}>

export async function ask(page: Page, text: string) {
  await page.getByPlaceholder(/Ask/).fill(text)
  await page.keyboard.press("Enter")
}

export async function expectReply(page: Page, containing: string | RegExp) {
  await expect(page.locator(".h-prose").last()).toContainText(containing)
  // the run is over once its (hidden) end marker is in the message
  await expect(page.getByTestId("run-done").last()).toBeAttached()
}
