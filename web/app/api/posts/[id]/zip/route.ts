import { jsonError } from "@/lib/bff"
import { idOk, studio } from "../../../brands/_studio"

export const runtime = "nodejs"
export const maxDuration = 60

/** Every size of the post plus captions.txt, as one download. */
export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return idOk(id) ? studio(req, `/posts/${id}/zip`, { method: "GET", binary: true, timeoutMs: 55_000 }) : jsonError(400, "bad_request", "Invalid id.")
}
