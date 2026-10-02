/** The device's IANA timezone ("Asia/Kolkata"), or undefined if the browser won't say. */
export function deviceTimeZone(): string | undefined {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone
    return tz && /^[A-Za-z0-9_+\-/]{1,64}$/.test(tz) ? tz : undefined
  } catch {
    return undefined
  }
}

/** Shape check for a timezone a client sent (the backend validates it against tzdata). */
export const timeZoneOrUndefined = (v: unknown): string | undefined =>
  typeof v === "string" && /^[A-Za-z0-9_+\-/]{1,64}$/.test(v) ? v : undefined
