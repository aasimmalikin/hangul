import type { Metadata } from "next"
import { ApproveByLink } from "@/components/hangul/ApproveByLink"

// The link is a credential: never indexed, never sent on as a Referer (next.config.ts adds the headers too).
export const metadata: Metadata = {
  title: "Approve · Hangul",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
}

/**
 * /approve/<link>: the Approve / Reject page a scheduled task's email or
 * notification opens. No sign-in; the signed link names one waiting action.
 */
export default async function Page({ params, searchParams }: {
  params: Promise<{ token: string }>
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>
}) {
  const { token } = await params
  const { d } = await searchParams
  return <ApproveByLink token={token} chosen={d === "approve" || d === "reject" ? d : null} />
}
