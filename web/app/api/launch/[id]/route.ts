import { idOr400, userProxy } from "../../_user"

export const runtime = "nodejs"

/** The full plan with its numbers (polled while `status` is "sourcing"). */
export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return idOr400(id) ?? userProxy(req, `/launch/${id}`, { method: "GET" })
}

/** Edit assumptions or items: `{price?, units_per_day?, days_per_month?, working_capital_months?, variable?, items?, title?}`. */
export async function PATCH(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return idOr400(id) ?? userProxy(req, `/launch/${id}`, { method: "PATCH", body: await req.text() })
}

/** Hides the plan. */
export async function DELETE(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return idOr400(id) ?? userProxy(req, `/launch/${id}`, { method: "DELETE" })
}
