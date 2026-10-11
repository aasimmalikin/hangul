import { jsonError } from "@/lib/bff"
import { idOk, studio } from "../../../brands/_studio"

export const runtime = "nodejs"

/** A private link for the client to approve the post or ask for changes. */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return idOk(id) ? studio(req, `/posts/${id}/review-link`, { method: "POST" }) : jsonError(400, "bad_request", "Invalid id.")
}
