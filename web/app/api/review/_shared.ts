/** Shared by the client-review relays (no session: the signed link is the credential). */
export const TOKEN = /^[A-Za-z0-9_-]{8,200}\.[A-Za-z0-9_-]{20,100}$/
export const HEADERS = { "Cache-Control": "private, no-store", "X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer" }

export function client(req: Request): string {
  return (req.headers.get("x-forwarded-for") ?? "").split(",")[0].trim() || "direct"
}
