import { userProxy } from "../../_user"

export const runtime = "nodejs"

/** -> `{url}`: a short-lived Dodo Payments customer-portal link (cancel, card, invoices). */
export async function POST(req: Request) { return userProxy(req, "/billing/portal", { method: "POST" }) }
