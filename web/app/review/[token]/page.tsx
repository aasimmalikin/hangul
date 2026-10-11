import type { Metadata } from "next"
import { ReviewByLink } from "@/components/hangul/ReviewByLink"

// The link is a credential: never indexed, never sent on as a Referer.
export const metadata: Metadata = {
  title: "Review a post · Hangul",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
}

/**
 * /review/<link>: the page an agency's client opens to approve a post or ask for
 * changes. No sign-in; the signed link names one post (harness.brands.review).
 */
export default async function Page({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params
  return <ReviewByLink token={token} />
}
