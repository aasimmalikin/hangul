import { idOr400, userProxy } from "../../../_user"

export const runtime = "nodejs"

/** Log a day: `{day?, sales, bills?, closed?, partial?, promo?, add?, note?}` (day defaults to today, the user's time). */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return idOr400(id) ?? userProxy(req, `/business/${id}/days`, { method: "POST", body: await req.text() })
}
