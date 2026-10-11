import { jsonError } from "@/lib/bff"
import { idOk, studio } from "../../../brands/_studio"

export const runtime = "nodejs"
export const maxDuration = 60

/** The plan as a PDF or an Excel workbook (`?format=pdf|xlsx`). */
export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const format = new URL(req.url).searchParams.get("format") === "xlsx" ? "xlsx" : "pdf"
  return idOk(id)
    ? studio(req, `/launch/${id}/export?format=${format}`, { method: "GET", binary: true, timeoutMs: 30_000, bucket: "launch" })
    : jsonError(400, "bad_request", "Invalid id.")
}
