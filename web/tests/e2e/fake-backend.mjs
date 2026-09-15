/**
 * A stand-in for the FastAPI backend used by the e2e suite.
 *
 * It speaks the same HTTP + SSE contract as `harness.api` (bearer JWT,
 * /ask/stream events, /approve, /upload, /healthz, /quality) and lets a test
 * inject every failure the real thing can produce, keyed by the question:
 *
 *   "APPROVAL …"   run pauses on a destructive tool → approval_required
 *   "ASK …"        run pauses on ask_user → approval_required with options
 *   "DROP …"       stream some text, then close the socket without `done`
 *   "ERROR …"      stream an `error` event
 *   "SLOW …"       first token after 3 s (for the Stop button)
 *   "E500 / E429 / E401 / E422"   answer with that HTTP status, no stream
 *   "HISTORY …"    reply states how many history turns arrived
 *   anything else  "Reply to: <question>" with one search_docs tool call
 *
 * Every reply also names the caller (`user=<sub>`) so isolation between
 * concurrent users is observable. `POST /__control {"down": true}` makes
 * /healthz fail; `GET /__state` exposes counters for assertions.
 */
import http from "node:http"
import crypto from "node:crypto"

const PORT = Number(process.env.FAKE_BACKEND_PORT ?? 8765)
const SECRET = process.env.FASTAPI_JWT_SECRET ?? "e2e-service-secret"

const state = { down: false, approves: {}, executed: {}, uploads: [], asks: [], inFlight: {} }

function verify(req) {
  const h = req.headers.authorization ?? ""
  const tok = h.startsWith("Bearer ") ? h.slice(7) : ""
  const [hdr, body, sig] = tok.split(".")
  if (!hdr || !body || !sig) return null
  const expect = crypto.createHmac("sha256", SECRET).update(`${hdr}.${body}`).digest("base64url")
  if (expect !== sig) return null
  const payload = JSON.parse(Buffer.from(body, "base64url").toString())
  if (payload.exp && payload.exp * 1000 < Date.now()) return null
  return payload
}

const json = (res, status, obj, headers = {}) => {
  res.writeHead(status, { "Content-Type": "application/json", ...headers })
  res.end(JSON.stringify(obj))
}
const readBody = (req) => new Promise((resolve) => {
  const chunks = []
  req.on("data", (c) => chunks.push(c))
  req.on("end", () => resolve(Buffer.concat(chunks)))
})
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function askStream(req, res, user) {
  const body = JSON.parse((await readBody(req)).toString() || "{}")
  const q = String(body.question ?? "")
  const history = Array.isArray(body.history) ? body.history : []
  state.asks.push({ user: user.sub, question: q, history: history.length, docs_only: body.docs_only === true })

  const m = q.match(/^(E\d{3})\b/)
  if (m) {
    const code = Number(m[1].slice(1))
    return json(res, code, { detail: `injected ${code}` }, code === 429 ? { "Retry-After": "7" } : {})
  }

  state.inFlight[user.sub] = (state.inFlight[user.sub] ?? 0) + 1
  const runId = "run-" + crypto.randomUUID().slice(0, 8)
  res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive" })
  const send = (event, data) => res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)
  const block = `${runId}:1`
  const finish = () => { state.inFlight[user.sub] -= 1 }
  req.on("close", finish)

  try {
    if (q.startsWith("SLOW")) await sleep(3000)
    send("step", { step: 1 })

    if (q.startsWith("ERROR")) { send("error", { message: "injected agent failure" }); return res.end() }

    send("text_start", { block })
    const reply = q.startsWith("HISTORY")
      ? `history=${history.length} user=${user.sub}`
      : `Reply to: ${q} user=${user.sub}${body.docs_only ? " docs_only=true" : ""}`
    for (const word of reply.split(" ")) { send("text_delta", { block, text: word + " " }); await sleep(15) }

    if (q.startsWith("DROP")) { res.destroy(); return }
    send("text_end", { block })

    if (q.startsWith("APPROVAL") || q.startsWith("ASK")) {
      const isAsk = q.startsWith("ASK")
      state.approves[runId] = { user: user.sub, pending: true }
      send("tool_call", { id: "c1", name: isAsk ? "ask_user" : "filesystem__write_file", arguments: isAsk ? { question: "Which format?", options: [{ label: "Markdown", description: "" }, { label: "Plain text", description: "" }] } : { path: "notes.txt" }, step: 1 })
      send("tool_result", { id: "c1", name: isAsk ? "ask_user" : "filesystem__write_file", ok: true, preview: "Waiting for your approval.", ms: 0, cached: false })
      send("approval_required", { run_id: runId, name: isAsk ? "ask_user" : "filesystem__write_file", arguments: isAsk ? { question: "Which format?", options: [{ label: "Markdown", description: "" }, { label: "Plain text", description: "" }] } : { path: "notes.txt" }, tool_call_id: "c1" })
      send("done", { steps: 1, run_id: runId, cost_usd: 0.001, tools_used: [isAsk ? "ask_user" : "filesystem__write_file"] })
      return res.end()
    }

    send("tool_call", { id: "c1", name: "search_docs", arguments: { query: q.slice(0, 40) }, step: 1 })
    await sleep(30)
    send("tool_result", { id: "c1", name: "search_docs", ok: true, preview: "…chunk…", ms: 42, cached: false })
    send("done", { steps: 2, run_id: runId, cost_usd: 0.0021, tools_used: ["search_docs"] })
    res.end()
  } finally {
    req.off("close", finish)
    finish()
  }
}

async function approve(req, res, user) {
  const body = JSON.parse((await readBody(req)).toString() || "{}")
  const a = state.approves[body.approval_id]
  // Same semantics as CheckpointStore.claim_pending: wrong user or already
  // claimed both read as "nothing pending".
  if (!a || a.user !== user.sub || !a.pending) return json(res, 404, { detail: "No pending action for that approval id." })
  a.pending = false
  await sleep(150) // window for a double-click to arrive
  state.executed[body.approval_id] = (state.executed[body.approval_id] ?? 0) + 1
  const answer = body.choice ? `You chose ${body.choice}.` : body.decision === "approve" ? "Wrote notes.txt." : "Okay, I won't write the file."
  json(res, 200, { answer, run_id: body.approval_id, prompt_version: "v", steps: 2, stopped_reason: "answered", cached: false })
}

async function upload(req, res, user) {
  const buf = await readBody(req)
  const nameMatch = buf.toString("latin1").match(/filename="([^"]+)"/)
  const filename = nameMatch ? nameMatch[1] : "upload"
  state.uploads.push({ user: user.sub, filename, bytes: buf.length })
  json(res, 200, { session_id: user.sub, filename, chunks_indexed: 7, mcp_path: `${user.sub}/${filename}`, message: "ok" })
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://x")
  if (url.pathname === "/__control" && req.method === "POST") {
    Object.assign(state, JSON.parse((await readBody(req)).toString() || "{}"))
    return json(res, 200, { ok: true })
  }
  if (url.pathname === "/__state") return json(res, 200, state)
  if (url.pathname === "/__reset") { Object.assign(state, { down: false, approves: {}, executed: {}, uploads: [], asks: [], inFlight: {} }); return json(res, 200, { ok: true }) }
  if (url.pathname === "/healthz") return state.down ? json(res, 503, { status: "down" }) : json(res, 200, { status: "ok" })
  if (url.pathname === "/quality") return json(res, 200, { available: true, avg_correctness: 0.91, avg_faithfulness: 0.88, pass_rate: 0.9, cases: 20, gate_passed: true, blocking_failures: [], advisory_notes: [] })

  const user = verify(req)
  if (!user) return json(res, 401, { detail: "invalid token" })
  if (state.down) return json(res, 503, { detail: "backend down" })

  if (url.pathname === "/ask/stream" && req.method === "POST") return askStream(req, res, user)
  if (url.pathname === "/approve" && req.method === "POST") return approve(req, res, user)
  if (url.pathname === "/upload" && req.method === "POST") return upload(req, res, user)
  json(res, 404, { detail: "not found" })
})

server.listen(PORT, "127.0.0.1", () => console.log(`fake backend on http://127.0.0.1:${PORT}`))
