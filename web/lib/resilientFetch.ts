// Auth.js does the OAuth token/userinfo exchange server-side with one
// un-retried fetch. From WSL2 the single IP behind oauth2.googleapis.com
// drops ~40% of fresh TCP handshakes, which surfaces as
// `CallbackRouteError: fetch failed (ETIMEDOUT)` and a bogus
// `?error=Configuration` redirect. A dropped SYN is transient, so retry
// connection-level failures a few times before giving up.

const TRANSIENT = new Set(["ETIMEDOUT", "ECONNRESET", "ECONNREFUSED", "EAI_AGAIN", "UND_ERR_CONNECT_TIMEOUT"])

function isTransient(err: unknown): boolean {
  const cause = (err as { cause?: { code?: string } })?.cause
  return err instanceof Error && err.name !== "AbortError" && (cause?.code === undefined || TRANSIENT.has(cause.code))
}

export async function resilientFetch(input: RequestInfo | URL, init?: RequestInit, attempts = 4): Promise<Response> {
  let lastErr: unknown
  for (let i = 0; i < attempts; i++) {
    try {
      return await fetch(input, { ...init, signal: init?.signal ?? AbortSignal.timeout(8000) })
    } catch (err) {
      lastErr = err
      if (!isTransient(err) || i === attempts - 1) break
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url
      console.warn(`[auth] fetch ${url} failed (${(err as { cause?: { code?: string } }).cause?.code ?? (err as Error).message}); retry ${i + 1}/${attempts - 1}`)
      await new Promise((r) => setTimeout(r, 250 * (i + 1)))
    }
  }
  throw lastErr
}
