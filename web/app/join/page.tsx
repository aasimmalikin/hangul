import type { Metadata } from "next"
import { JoinWaitlist } from "@/components/hangul/JoinWaitlist"

export const metadata: Metadata = {
  title: "Pre-register · Hangul",
  description: "Hangul is the AI assistant that talks first, keeps every promise in one place, and never acts without your tap. Pre-register to be a founding member.",
}

/**
 * /join: pre-registration before launch. Public. `?ref=` (or `utm_source=`)
 * records where the visitor came from, e.g. /join?ref=x for links posted on X.
 */
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams
  const first = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? ""
  return <JoinWaitlist source={first(sp.ref) || first(sp.utm_source)} />
}
