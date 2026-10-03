import { userProxy } from "../../_user"

export const runtime = "nodejs"

/** The first-run walkthrough is finished or skipped. */
export async function POST(req: Request) { return userProxy(req, "/settings/onboarded", { method: "POST" }) }
