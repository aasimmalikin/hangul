import { auth } from "@/auth"
import { mintServiceToken } from "@/lib/service-token"

/**
 * Shared guard rails for the BFF routes (/api/chat, /api/upload, /api/approve,
 * /api/health, /api/quality). Every route goes through the same steps so a
 * change here — a new header, a new limit — reaches all of them:
 *
 *   1. same-origin check      browsers only; blocks cross-site POSTs
 *   2. session                401 with a stable `code` the UI can act on
 *   3. per-user rate limit    429 + Retry-After
 *   4. upstream fetch         bounded by a timeout; connection failures and
 *                             timeouts become 502/504 JSON, never a hung request
 *
 * Error bodies are always `{ detail, code }` so the client can branch on
 * `code` instead of parsing prose.
 */

export type BffErrorCode =
  | "unauthorized"
  | "forbidden_origin"
  | "rate_limited"
  | "bad_request"
  | "upstream_unreachable"
  | "upstream_timeout"
  | "upstream_error"

export function jsonError(status: number, code: BffErrorCode, detail: string, headers: Record<string, string> = {}) {
  return Response.json({ detail, code }, { status, headers })
}

// ---------------------------------------------------------------- origin

/**
 * State-changing routes must only be called by our own pages. Browsers send
 * `Sec-Fetch-Site` on every request; anything but same-origin/none is a
 * cross-site call (a malicious page trying to ride the user's cookie). Older
 * clients without the header fall back to comparing Origin with Host.
 */
export function assertSameOrigin(req: Request): Response | null {
  const site = req.headers.get("sec-fetch-site")
  if (site) {
    return site === "same-origin" || site === "none" ? null : jsonError(403, "forbidden_origin", "Cross-site request blocked.")
  }
  const origin = req.headers.get("origin")
  if (!origin) return null // non-browser client (curl, tests); auth still applies
  const host = req.headers.get("x-forwarded-host") ?? req.headers.get("host")
  try {
    if (new URL(origin).host === host) return null
  } catch { /* fall through */ }
  return jsonError(403, "forbidden_origin", "Cross-site request blocked.")
}

// --------------------------------------------------------------- session

export async function requireUser(): Promise<{ userId: string } | Response> {
  const session = await auth()
  const userId = session?.user?.id
  if (!userId) return jsonError(401, "unauthorized", "Sign in to continue.")
  return { userId }
}

// ------------------------------------------------------------ rate limit

type Bucket = { count: number; resetAt: number }
const buckets = new Map<string, Bucket>()

/**
 * Fixed-window limiter keyed by user + route. In-memory, so it is per
 * server instance: with N instances the effective limit is N× — still a
 * bound, and the backend has its own per-user in-flight cap behind it.
 */
export function rateLimit(key: string, limit: number, windowMs: number): Response | null {
  const now = Date.now()
  let b = buckets.get(key)
  if (!b || b.resetAt <= now) {
    b = { count: 0, resetAt: now + windowMs }
    buckets.set(key, b)
    if (buckets.size > 10_000) {
      for (const [k, v] of buckets) if (v.resetAt <= now) buckets.delete(k)
    }
  }
  b.count += 1
  if (b.count > limit) {
    const retry = Math.max(1, Math.ceil((b.resetAt - now) / 1000))
    return jsonError(429, "rate_limited", `Too many requests. Try again in ${retry}s.`, { "Retry-After": String(retry) })
  }
  return null
}

// -------------------------------------------------------------- upstream

export class UpstreamError extends Error {
  constructor(public readonly status: number, public readonly code: BffErrorCode, message: string) {
    super(message)
  }
}

/**
 * Fetch from FastAPI with a service token and a hard timeout. Throws
 * UpstreamError for connection failures / timeouts; returns the Response
 * for anything the backend actually answered (including 4xx/5xx), so the
 * caller decides how to relay it.
 */
export async function upstream(
  path: string,
  userId: string,
  init: RequestInit,
  { timeoutMs, signal }: { timeoutMs: number; signal?: AbortSignal },
): Promise<Response> {
  const base = process.env.FASTAPI_URL
  if (!base) throw new UpstreamError(502, "upstream_unreachable", "Assistant backend is not configured.")

  const token = await mintServiceToken(userId, "user")
  const signals = [AbortSignal.timeout(timeoutMs), ...(signal ? [signal] : [])]

  try {
    return await fetch(`${base}${path}`, {
      ...init,
      headers: { ...(init.headers ?? {}), Authorization: `Bearer ${token}` },
      signal: AbortSignal.any(signals),
    })
  } catch (e) {
    const err = e as Error & { cause?: { code?: string } }
    if (err.name === "TimeoutError") {
      throw new UpstreamError(504, "upstream_timeout", "The assistant took too long to respond.")
    }
    if (err.name === "AbortError") throw err // caller went away; let it propagate
    throw new UpstreamError(502, "upstream_unreachable", "The assistant is unreachable right now.")
  }
}

/** Relay a non-2xx backend answer as `{detail, code}` with a client-actionable code. */
export async function relayUpstreamError(res: Response): Promise<Response> {
  let detail = `The assistant returned an error (${res.status}).`
  try {
    const body = await res.json()
    if (typeof body?.detail === "string") detail = body.detail
  } catch { /* not JSON */ }
  const code: BffErrorCode =
    res.status === 401 ? "unauthorized"
    : res.status === 429 ? "rate_limited"
    : res.status === 502 || res.status === 503 || res.status === 504 ? "upstream_unreachable"
    : res.status === 404 || res.status === 400 || res.status === 413 || res.status === 422 ? "bad_request"
    : "upstream_error"
  const headers: Record<string, string> = {}
  const ra = res.headers.get("retry-after")
  if (ra) headers["Retry-After"] = ra
  // A 401 from the backend means our short-lived service token was rejected,
  // not that the user's session is bad — surface it as a backend fault.
  const status = res.status === 401 ? 502 : res.status
  return jsonError(status, res.status === 401 ? "upstream_error" : code, detail, headers)
}
