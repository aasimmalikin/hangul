import { jsonError } from "@/lib/bff"
import { idOk, studio } from "../../../brands/_studio"

export const runtime = "nodejs"
export const maxDuration = 60

const MAX = 10 * 1024 * 1024
const TYPES = new Set([".xlsx", ".xls", ".csv"])

/** A sales report (Excel/CSV) from a billing app, Tally, Petpooja or a UPI statement. Fields: file, date_col?, amount_col?, replace?, preview?. */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  if (!idOk(id)) return jsonError(400, "bad_request", "Invalid id.")
  if (Number(req.headers.get("content-length") ?? 0) > MAX + 8192) return jsonError(413, "bad_request", "The file can be up to 10 MB.")
  let incoming: FormData
  try {
    incoming = await req.formData()
  } catch {
    return jsonError(400, "bad_request", "Malformed upload.")
  }
  const file = incoming.get("file")
  if (!(file instanceof File) || file.size === 0) return jsonError(400, "bad_request", "No file provided.")
  const name = file.name.replace(/[/\\]/g, "_").slice(0, 200) || "sales.xlsx"
  const ext = name.includes(".") ? "." + name.split(".").pop()!.toLowerCase() : ""
  if (!TYPES.has(ext)) return jsonError(400, "bad_request", "Upload the sales report as Excel (.xlsx) or CSV.")
  if (file.size > MAX) return jsonError(413, "bad_request", "The file can be up to 10 MB.")
  const form = new FormData()
  form.append("file", file, name)
  for (const k of ["date_col", "amount_col", "replace", "preview"]) {
    const v = incoming.get(k)
    if (typeof v === "string" && v.length <= 120) form.append(k, v)
  }
  return studio(req, `/business/${id}/import`, { method: "POST", body: form, timeoutMs: 45_000, bucket: "business", perMinute: 20 })
}
