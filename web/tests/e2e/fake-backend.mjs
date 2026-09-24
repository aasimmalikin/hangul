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
 *   "INJECT …"     security events: flagged tool result, stepped-up action, redacted answer
 *   "GMAIL …"      a Gmail search card (structured ui) then a send that pauses for approval
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

const state = { down: false, approves: {}, executed: {}, uploads: [], asks: [], inFlight: {}, memory: {}, episodes: {}, conversations: {}, convMessages: {}, adminCalls: [], evalRuns: {}, prefs: {}, tasks: {}, google: {} }

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

// A stand-in for the backend model registry (`GET /models`): one reasoning
// model (the default) and one that takes no effort, so the picker's
// show/hide of the effort chip is exercised.
const MODELS = {
  default: { model: "fake-reasoner", effort: "medium" },
  models: [
    { id: "fake-reasoner", label: "Fake Reasoner", input_usd_per_m: 5, output_usd_per_m: 30,
      supports_reasoning: true, efforts: ["low", "medium", "high"], default_effort: "medium" },
    { id: "fake-plain", label: "Fake Plain", input_usd_per_m: 2, output_usd_per_m: 8,
      supports_reasoning: false, efforts: [], default_effort: null },
  ],
}

async function askStream(req, res, user) {
  const body = JSON.parse((await readBody(req)).toString() || "{}")
  const q = String(body.question ?? "")
  const history = Array.isArray(body.history) ? body.history : []
  state.asks.push({ user: user.sub, question: q, history: history.length, conversation_id: body.conversation_id ?? null,
                    docs_only: body.docs_only === true, connectors: body.connectors ?? [], mode: body.mode ?? "default",
                    model: body.model ?? null, effort: body.effort ?? null })

  const m = q.match(/^(E\d{3})\b/)
  if (m) {
    const code = Number(m[1].slice(1))
    return json(res, code, { detail: `injected ${code}` }, code === 429 ? { "Retry-After": "7" } : {})
  }

  // The conversation this turn belongs to. An existing id continues that chat
  // (409 if it already has a run in flight); no id starts one, exactly as
  // harness.api.routes.ask does.
  let convRow = null
  if (body.conversation_id) {
    convRow = conversationsFor(user).find((c) => c.id === body.conversation_id && c.active)
    if (!convRow) return json(res, 404, { detail: "No such conversation." })
    if (convRow.busy) {
      return json(res, 409, { detail: "This conversation already has a run in flight." },
                  { "Retry-After": "5", "X-Reason": "conversation_busy" })
    }
  } else {
    convRow = newConversation(user, {
      model: body.model ?? null, effort: body.effort ?? null,
      connectors: Array.isArray(body.connectors) ? body.connectors : [],
      mode: body.mode ?? "default", docs_only: body.docs_only === true,
    })
  }
  if (!convRow.title) convRow.title = q.slice(0, 200)
  convRow.busy = true
  // The server owns the transcript: record the question now so a reopened chat
  // shows it even if the run never finishes.
  const transcript = messagesFor(convRow.id)
  transcript.push({ seq: transcript.length, role: "user", content: q })

  state.inFlight[user.sub] = (state.inFlight[user.sub] ?? 0) + 1
  const runId = "run-" + crypto.randomUUID().slice(0, 8)
  res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive" })
  // `done` and `approval_required` always carry the conversation id -- that is
  // how the tab learns which chat the server put this turn in.
  const send = (event, data) => {
    const payload = (event === "done" || event === "approval_required")
      ? { ...data, conversation_id: convRow.id }
      : data
    // Whatever text the run produced is the assistant turn in the transcript.
    if (event === "text_delta") lastText += data.text ?? ""
    res.write(`event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`)
  }
  let lastText = ""
  const block = `${runId}:1`
  const finish = () => {
    state.inFlight[user.sub] -= 1
    convRow.busy = false
    convRow.updated_at = new Date().toISOString()
    if (lastText) transcript.push({ seq: transcript.length, role: "assistant", content: lastText })
  }
  req.on("close", finish)

  try {
    send("step", { step: 1 })
    if (q.startsWith("SLOW")) await sleep(3000)

    if (q.startsWith("ERROR")) { send("error", { message: "injected agent failure" }); return res.end() }

    if (q.startsWith("GMAIL")) {
      // a Gmail search with a structured result, then a send that needs approval
      send("tool_call", { id: "c1", name: "gmail__search_messages", arguments: { query: "newer_than:1d" }, step: 1 })
      send("tool_result", { id: "c1", name: "gmail__search_messages", ok: true, preview: "2 message(s)", ms: 120, cached: false,
        ui: { kind: "gmail_messages", query: "newer_than:1d", messages: [
          { id: "m1", thread_id: "t1", from: "Alice Example <alice@example.com>", to: "me", subject: "Lunch tomorrow?", date: new Date().toISOString(), snippet: "Are you free around noon", labels: ["INBOX", "UNREAD"], unread: true },
          { id: "m2", thread_id: "t2", from: "billing@vendor.example", to: "me", subject: "Invoice 4471", date: "2026-09-10T09:00:00Z", snippet: "Your invoice is attached", labels: ["INBOX", "CATEGORY_UPDATES"], unread: false },
        ] } })
      state.approves[runId] = { user: user.sub, pending: true }
      const args = { to: "alice@example.com", subject: "Re: Lunch tomorrow?", body: "Noon works, see you there." }
      send("tool_call", { id: "c2", name: "gmail__send_message", arguments: args, step: 2 })
      send("tool_result", { id: "c2", name: "gmail__send_message", ok: true, preview: "Waiting for your approval.", ms: 0, cached: false })
      send("approval_required", { run_id: runId, name: "gmail__send_message", arguments: args, tool_call_id: "c2" })
      send("done", { steps: 2, run_id: runId, cost_usd: 0.002, tools_used: ["gmail__search_messages", "gmail__send_message"] })
      return res.end()
    }

    if (q.startsWith("INJECT")) {
      // a poisoned document: the tool-result screen fires, the outbound call is
      // stepped up to approval, and the output guard replaces the streamed answer
      send("tool_call", { id: "c1", name: "search_docs", arguments: { query: "revenue" }, step: 1 })
      send("tool_result", { id: "c1", name: "search_docs", ok: true, preview: "…IGNORE PREVIOUS…", ms: 12, cached: false })
      send("security", { layer: "tool_result", severity: "high", source: "search_docs", action: "flagged", reasons: ["override_instructions: 'ignore previous instructions'"], step: 1 })
      send("security", { layer: "action", severity: "medium", source: "web_search", action: "stepped_up", reasons: ["context tainted by search_docs; web_search needs your approval"], step: 2 })
      send("text_start", { block })
      for (const word of "The revenue was 48M and here is a leaked marker cnry-deadbeef".split(" ")) { send("text_delta", { block, text: word + " " }); await sleep(10) }
      send("text_end", { block })
      send("security", { layer: "output", severity: "high", source: "answer", action: "redacted", reasons: ["system prompt canary appeared in the answer"], step: 2, answer: "The revenue was 48M and here is a leaked marker [REDACTED]" })
      send("done", { steps: 2, run_id: runId, cost_usd: 0.002, tools_used: ["search_docs"] })
      return res.end()
    }

    send("text_start", { block })
    const reply = q.startsWith("HISTORY")
      ? `history=${history.length} user=${user.sub}`
      : `Reply to: ${q} user=${user.sub}${body.docs_only ? " docs_only=true" : ""}${body.model ? ` model=${body.model}` : ""}${body.effort ? ` effort=${body.effort}` : ""}`
    for (const word of reply.split(" ")) { send("text_delta", { block, text: word + " " }); await sleep(15) }

    if (q.startsWith("DROP")) { res.destroy(); return }
    send("text_end", { block })

    if (q.startsWith("APPROVAL") || q.startsWith("ASK")) {
      const isAsk = q.startsWith("ASK")
      state.approves[runId] = { user: user.sub, pending: true }
      const fileArgs = { path: "/sessions/notes.txt", content: "Line one of the notes.\nLine two, with a bit more detail.\nLine three closes it." }
      if (!isAsk) {
        // Stream the call the way the real provider does: name first, then
        // the JSON arguments in fragments, so the UI can show the draft.
        send("tool_pending", { id: "c1", name: "filesystem__write_file", step: 1 })
        const json = JSON.stringify(fileArgs)
        for (let i = 0; i < json.length; i += 9) { send("tool_args_delta", { id: "c1", text: json.slice(i, i + 9) }); await sleep(30) }
      }
      send("tool_call", { id: "c1", name: isAsk ? "ask_user" : "filesystem__write_file", arguments: isAsk ? { question: "Which format?", options: [{ label: "Markdown", description: "" }, { label: "Plain text", description: "" }] } : fileArgs, step: 1 })
      send("tool_result", { id: "c1", name: isAsk ? "ask_user" : "filesystem__write_file", ok: true, preview: "Waiting for your approval.", ms: 0, cached: false })
      send("approval_required", { run_id: runId, name: isAsk ? "ask_user" : "filesystem__write_file", arguments: isAsk ? { question: "Which format?", options: [{ label: "Markdown", description: "" }, { label: "Plain text", description: "" }] } : fileArgs, tool_call_id: "c1" })
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
  const poisoned = /poison/i.test(filename)
  json(res, 200, { session_id: user.sub, filename, chunks_indexed: 7, mcp_path: `${user.sub}/${filename}`, message: "ok",
    security: { suspicious_chunks: poisoned ? 2 : 0, hidden_chars: 0, warning: poisoned ? "2 passage(s) in this file read like instructions to the assistant. They will be treated as data, not followed." : null } })
}

/**
 * Memory rows per user, seeded on first read so every fresh user starts with
 * the same three. DELETE deactivates (like the real backend) — the row stays
 * in state with active:false so a test can assert it was not erased.
 */
function memoryFor(user) {
  if (!state.memory[user.sub]) {
    state.memory[user.sub] = [
      { id: 3, kind: "correction", content: "Call me Sam, not Samuel", active: true, created_at: "2026-09-17T09:00:00Z" },
      { id: 2, kind: "fact", content: "Works on the billing service", active: true, created_at: "2026-09-16T09:00:00Z" },
      { id: 1, kind: "preference", content: "Prefers short answers with code samples", active: true, created_at: "2026-09-10T09:00:00Z" },
    ]
  }
  return state.memory[user.sub]
}

/**
 * Chat history (episodes) per user, empty until the app saves one. POST is
 * an upsert by thread_id, DELETE deactivates — same contract as
 * harness.api.routes.episodes, minus the embedding.
 */
let episodeSeq = 0
function episodesFor(user) {
  return (state.episodes[user.sub] ??= [])
}
/**
 * Conversations per user: the server-owned chat the app lists, reopens and
 * continues. Same contract as harness.api.routes.conversations. `convMessages`
 * is the transcript, in OpenAI wire shape, so a reopened chat rehydrates from
 * it exactly as it would in production.
 */
let convSeq = 0
function conversationsFor(user) {
  return (state.conversations[user.sub] ??= [])
}
function messagesFor(conversationId) {
  return (state.convMessages[conversationId] ??= [])
}
function newConversation(user, fields = {}) {
  const now = new Date().toISOString()
  // 32 hex chars, like uuid4().hex on the backend (the BFF checks the shape).
  const id = (++convSeq).toString(16).padStart(32, "0")
  const row = { id, title: "", model: null, effort: null, connectors: [], mode: "default",
                docs_only: false, preview: "", created_at: now, updated_at: now, active: true, ...fields }
  conversationsFor(user).push(row)
  return row
}
function conversationItem(row, count) {
  const { id, title, preview, model, effort, connectors, mode, docs_only, created_at, updated_at } = row
  return { id, title, preview, model, effort, connectors, mode, docs_only, message_count: count, created_at, updated_at }
}

// Same one-line description the real route derives: first answer, else first question.
function preview(summary) {
  const lines = summary.split("\n").map((l) => l.trim()).filter(Boolean)
  const pick = lines.find((l) => l.startsWith("A:")) ?? lines.find((l) => l.startsWith("Q:")) ?? ""
  const text = pick.slice(2).split(/\s+/).join(" ").trim()
  return text.length <= 160 ? text : text.slice(0, 159).trimEnd() + "…"
}


// ---- admin page fixtures
/** The one email the fake backend treats as an operator (the real one is settings.admin_emails). */
const ADMIN_EMAIL = "operator@example.com"
const ADMIN = {
  catalog: {
    suites: { qa: "Answer quality", tool_selection: "Tool selection and friends" },
    evals: [
      { key: "tool_choice", name: "Tool choice", category: "tool_use", status: "available", description: "Right tools called.", metrics: ["avg_tool_choice"], grader: "deterministic", suite: "tool_selection", needs: "" },
      { key: "qa_correctness", name: "Answer correctness", category: "quality", status: "available", description: "Judge vs reference.", metrics: ["avg_correctness"], grader: "judge", suite: "qa", needs: "" },
      { key: "multi_turn", name: "Multi-turn fidelity", category: "conversation", status: "planned", description: "Goal drift.", metrics: [], grader: "mixed", suite: null, needs: "scripted conversations" },
    ],
  },
  summary: {
    qa: { available: true, n: 20, metrics: { avg_correctness: 0.91, avg_faithfulness: 0.88, pass_rate: 0.9 }, prompt_version: "abc123", model: "gpt-5.5", gate: { passed: true, blocking_failures: [], advisory_notes: [] } },
    tool_selection: { available: true, n: 14, metrics: { avg_tool_choice: 0.86, avg_tool_necessity: 0.79, avg_hallucination: 0.93, avg_separation_of_concerns: 0.9, pass_rate: 0.64, avg_cost_usd: 0.0031 }, prompt_version: "abc123", model: "gpt-5.5" },
  },
  runs: [{ file: "tool_selection-20260918-100000.json", suite: "tool_selection", created: "20260918-100000", n: 14, metrics: { avg_tool_choice: 0.86 }, prompt_version: "abc123", model: "gpt-5.5" }],
  report: { suite: "tool_selection", n: 1, metrics: { avg_tool_choice: 0.86 }, prompt_version: "abc123", model: "gpt-5.5",
    cases: [{ id: "ts01", question: "revenue?", concern: "docs", expected_tools: ["search_docs"], tools_called: ["search_docs", "web_search"],
      scores: { tool_choice: 0.67, tool_necessity: 0.5, hallucination: 1, separation_of_concerns: 0.5, argument_correctness: 1, approval_compliance: 1, notes: ["unexpected ['web_search']"], judge_reason: "" } }] },
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://x")
  if (url.pathname === "/__control" && req.method === "POST") {
    Object.assign(state, JSON.parse((await readBody(req)).toString() || "{}"))
    return json(res, 200, { ok: true })
  }
  if (url.pathname === "/__google" && req.method === "POST") {
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    state.google[String(b.user)] = { connected: true, products: ["gmail", "calendar", "drive", "docs"], scopes: [] }
    return json(res, 200, { ok: true })
  }
  if (url.pathname === "/__state") return json(res, 200, state)
  // Test hook: plant a server-owned conversation (and optionally its transcript)
  // for a user, with a chosen timestamp -- what the rail reads.
  if (url.pathname === "/__conversation" && req.method === "POST") {
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    const at = b.updated_at ?? new Date().toISOString()
    const row = newConversation({ sub: String(b.user) }, { title: b.title, created_at: at, updated_at: at })
    const msgs = Array.isArray(b.messages) && b.messages.length
      ? b.messages
      : [{ role: "user", content: b.title }, { role: "assistant", content: `Reply to: ${b.title}` }]
    messagesFor(row.id).push(...msgs.map((m, i) => ({ seq: i, role: m.role, content: m.content })))
    return json(res, 200, { ok: true, id: row.id })
  }
  // Test hook: plant a conversation for a user with a chosen timestamp.
  if (url.pathname === "/__episode" && req.method === "POST") {
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    const rows = episodesFor({ sub: String(b.user) })
    const at = b.updated_at ?? new Date().toISOString()
    rows.push({ id: ++episodeSeq, thread_id: b.thread_id ?? `seed-${episodeSeq}`, title: b.title, summary: b.summary ?? `Q: ${b.title}\nA: Reply to: ${b.title}`, created_at: at, updated_at: at, active: true })
    return json(res, 200, { ok: true })
  }
  if (url.pathname === "/__reset") { Object.assign(state, { down: false, approves: {}, executed: {}, uploads: [], asks: [], inFlight: {}, memory: {}, episodes: {}, conversations: {}, convMessages: {}, adminCalls: [], evalRuns: {}, prefs: {}, tasks: {}, google: {} }); convSeq = 0; return json(res, 200, { ok: true }) }
  if (url.pathname === "/healthz") return state.down ? json(res, 503, { status: "down" }) : json(res, 200, { status: "ok" })
  if (url.pathname === "/connectors") return json(res, 200, [
    { key: "arxiv", label: "Research", description: "Search and read arXiv papers", kind: "builtin", icon: "book-2", per_user: false, auth: null, servers: [] },
    { key: "google", label: "Google Workspace", description: "Gmail, Calendar, Drive and Docs", kind: "mcp", icon: "brand-google", per_user: true, auth: "google", servers: ["gmail", "calendar", "drive", "docs"] },
  ])
  if (url.pathname === "/quality") return json(res, 200, { available: true, avg_correctness: 0.91, avg_faithfulness: 0.88, pass_rate: 0.9, cases: 20, gate_passed: true, blocking_failures: [], advisory_notes: [] })

  const user = verify(req)
  if (!user) return json(res, 401, { detail: "invalid token" })
  if (state.down) return json(res, 503, { detail: "backend down" })
  if (url.pathname === "/models" && req.method === "GET") return json(res, 200, MODELS)

  if (url.pathname === "/ask/stream" && req.method === "POST") return askStream(req, res, user)
  if (url.pathname === "/approve" && req.method === "POST") return approve(req, res, user)
  if (url.pathname === "/upload" && req.method === "POST") return upload(req, res, user)
  if (url.pathname === "/memory" && req.method === "GET") {
    return json(res, 200, memoryFor(user).filter((m) => m.active).map(({ id, kind, content, created_at }) => ({ id, kind, content, created_at })))
  }
  if (url.pathname === "/conversations" && req.method === "GET") {
    const rows = conversationsFor(user).filter((c) => c.active)
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    return json(res, 200, rows.map((r) => conversationItem(r, messagesFor(r.id).length)))
  }
  if (url.pathname === "/conversations" && req.method === "POST") {
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    const row = newConversation(user, {
      title: (b.title ?? "").slice(0, 200), model: b.model ?? null, effort: b.effort ?? null,
      connectors: Array.isArray(b.connectors) ? b.connectors : [],
      mode: b.mode === "research" ? "research" : "default", docs_only: b.docs_only === true,
    })
    return json(res, 201, { id: row.id })
  }
  const conv = url.pathname.match(/^\/conversations\/([0-9a-f]{1,64})$/)
  if (conv) {
    const row = conversationsFor(user).find((c) => c.id === conv[1] && c.active)
    // A foreign or unknown id is a 404, never a 403 -- the real route is the same.
    if (!row) return json(res, 404, { detail: "conversation not found" })
    if (req.method === "GET") {
      const msgs = messagesFor(row.id)
      return json(res, 200, { ...conversationItem(row, msgs.length), messages: msgs })
    }
    if (req.method === "PATCH") {
      const b = JSON.parse((await readBody(req)).toString() || "{}")
      if (typeof b.title !== "string" || !b.title.trim()) return json(res, 422, { detail: "invalid" })
      row.title = b.title.slice(0, 200)
      row.updated_at = new Date().toISOString()
      return json(res, 200, { id: row.id, title: row.title })
    }
    if (req.method === "DELETE") {
      row.active = false
      return json(res, 200, { deleted: row.id })
    }
  }
  if (url.pathname === "/episodes" && req.method === "GET") {
    const rows = episodesFor(user).filter((e) => e.active).sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    return json(res, 200, rows.map(({ id, thread_id, title, summary, created_at, updated_at }) => ({ id, thread_id, title, preview: preview(summary), summary, created_at, updated_at })))
  }
  if (url.pathname === "/episodes" && req.method === "POST") {
    const body = JSON.parse((await readBody(req)).toString() || "{}")
    if (!body.thread_id || !body.title || !body.summary) return json(res, 422, { detail: "invalid" })
    const rows = episodesFor(user)
    const now = new Date().toISOString()
    let row = rows.find((e) => e.thread_id === body.thread_id)
    if (!row) { row = { id: ++episodeSeq, thread_id: body.thread_id, created_at: now, active: true }; rows.push(row) }
    Object.assign(row, { title: body.title, summary: body.summary, updated_at: now, active: true })
    return json(res, 201, { id: row.id, thread_id: row.thread_id })
  }
  const edel = url.pathname.match(/^\/episodes\/(\d+)$/)
  if (edel && req.method === "DELETE") {
    const row = episodesFor(user).find((e) => e.id === Number(edel[1]) && e.active)
    if (!row) return json(res, 404, { detail: "conversation not found" })
    row.active = false
    return json(res, 200, { deleted: row.id })
  }
  const del = url.pathname.match(/^\/memory\/(\d+)$/)
  if (del && req.method === "DELETE") {
    const row = memoryFor(user).find((m) => m.id === Number(del[1]) && m.active)
    if (!row) return json(res, 404, { detail: "memory not found" })
    row.active = false
    return json(res, 200, { deleted: row.id })
  }
  // ---- personalisation, scheduled tasks, integrations (per user)
  if (url.pathname === "/settings" && req.method === "GET") {
    return json(res, 200, { display_name: "", instructions: "", tone: "balanced", timezone: "UTC", language: "", ...(state.prefs[user.sub] ?? {}), tones: ["concise", "balanced", "detailed"] })
  }
  if (url.pathname === "/settings" && req.method === "PUT") {
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    if (!["concise", "balanced", "detailed"].includes(b.tone ?? "balanced")) return json(res, 422, { detail: "bad tone" })
    state.prefs[user.sub] = { display_name: b.display_name ?? "", instructions: b.instructions ?? "", tone: b.tone ?? "balanced", timezone: b.timezone ?? "UTC", language: b.language ?? "" }
    return json(res, 200, state.prefs[user.sub])
  }
  const userTasks = () => Object.values(state.tasks).filter((t) => t.user === user.sub)
  const pub = (t) => Object.fromEntries(Object.entries(t).filter(([k]) => k !== "user"))
  if (url.pathname === "/tasks" && req.method === "GET") return json(res, 200, userTasks().map(pub))
  if (url.pathname === "/tasks" && req.method === "POST") {
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    if (!(b.every_minutes || b.daily_at)) return json(res, 422, { detail: "a schedule needs every_minutes or daily_at" })
    const id = Object.keys(state.tasks).length + 1
    state.tasks[id] = { id, user: user.sub, title: b.title, question: b.question, every_minutes: b.every_minutes ?? null, daily_at: b.daily_at ?? null,
      connectors: b.connectors ?? [], mode: b.mode ?? "default", enabled: true, next_run_at: new Date(Date.now() + 3600e3).toISOString(),
      last_run_at: null, last_status: "never", last_run_id: null, last_answer: "", created_at: new Date().toISOString() }
    return json(res, 201, pub(state.tasks[id]))
  }
  const trun = url.pathname.match(/^\/tasks\/(\d+)\/run$/)
  if (trun && req.method === "POST") {
    const t = state.tasks[trun[1]]
    if (!t || t.user !== user.sub) return json(res, 404, { detail: "task not found" })
    const pause = t.question.startsWith("APPROVAL")
    if (pause) state.approves["run-task"] = { user: user.sub, pending: true }
    Object.assign(t, { last_status: pause ? "needs_approval" : "done", last_run_at: new Date().toISOString(), last_run_id: "run-task", last_answer: pause ? "" : `Ran: ${t.question}` })
    return json(res, 200, pub(t))
  }
  const ten = url.pathname.match(/^\/tasks\/(\d+)\/enabled$/)
  if (ten && req.method === "POST") {
    const t = state.tasks[ten[1]]
    if (!t || t.user !== user.sub) return json(res, 404, { detail: "task not found" })
    t.enabled = url.searchParams.get("enabled") === "true"
    return json(res, 200, pub(t))
  }
  const tdel = url.pathname.match(/^\/tasks\/(\d+)$/)
  if (tdel && req.method === "DELETE") {
    const t = state.tasks[tdel[1]]
    if (!t || t.user !== user.sub) return json(res, 404, { detail: "task not found" })
    delete state.tasks[tdel[1]]
    return json(res, 200, { deleted: Number(tdel[1]) })
  }
  if (url.pathname === "/integrations" && req.method === "GET") {
    return json(res, 200, { google: state.google[user.sub] ?? { connected: false, products: [], scopes: [] } })
  }
  if (url.pathname === "/integrations/google" && req.method === "DELETE") { delete state.google[user.sub]; return json(res, 200, { disconnected: true }) }

  // ---- admin: only a service token with role=admin gets in (mirrors require_admin)
  if (url.pathname.startsWith("/admin/")) {
    // mirrors harness.api.auth.require_admin: allowlisted email + Google + recent sign-in
    if (!user.email || user.email.toLowerCase() !== ADMIN_EMAIL) return json(res, 403, { detail: "email not authorised" })
    if (user.auth_provider !== "google") return json(res, 403, { detail: "google sign-in required" })
    if (typeof user.auth_at !== "number" || Date.now() / 1000 - user.auth_at > 12 * 3600) return json(res, 401, { detail: "sign-in too old, re-authenticate" })
    state.adminCalls.push({ user: user.sub, email: user.email, path: url.pathname, method: req.method })
    if (url.pathname === "/admin/whoami") return json(res, 200, { authorized: true, email: user.email, auth_provider: "google", auth_at: user.auth_at, max_auth_age_s: 43200, allowlist_size: 1 })
    if (url.pathname === "/admin/evals/catalog") return json(res, 200, ADMIN.catalog)
    if (url.pathname === "/admin/evals/summary") return json(res, 200, { suites: ADMIN.summary, running: state.evalRuns })
    if (url.pathname === "/admin/evals/status") return json(res, 200, state.evalRuns)
    if (url.pathname === "/admin/evals/runs") return json(res, 200, ADMIN.runs)
    const rep = url.pathname.match(/^\/admin\/evals\/runs\/([a-z_]+-\d{8}-\d{6}\.json)$/)
    if (rep) return rep[1] === ADMIN.runs[0].file ? json(res, 200, ADMIN.report) : json(res, 404, { detail: "report not found" })
    if (url.pathname === "/admin/evals/run" && req.method === "POST") {
      const b = JSON.parse((await readBody(req)) || "{}")
      if (!ADMIN.catalog.suites[b.suite]) return json(res, 422, { detail: `unknown suite '${b.suite}'` })
      if (state.evalRuns[b.suite]?.state === "running") return json(res, 409, { detail: `${b.suite} is already running` })
      state.evalRuns[b.suite] = { suite: b.suite, state: "running", started_at: Date.now() / 1000, started_by: user.sub, finished_at: null, file: null, error: null }
      return json(res, 202, state.evalRuns[b.suite])
    }
    if (url.pathname.startsWith("/admin/security")) return json(res, 200, {
      total: 2, by_layer: { tool_result: 1, output: 1 }, by_severity: { medium: 1, high: 1 }, by_action: { flagged: 1, redacted: 1 },
      top_sources: [["search_docs", 1]],
      recent: [{ ts: Date.now() / 1000, layer: "tool_result", severity: "medium", source: "search_docs", action: "flagged", reasons: ["override_instructions: 'ignore previous instructions'"] }],
      config: { llm_screen: false, offender_limit: 5 },
    })
    if (url.pathname === "/admin/overview") return json(res, 200, { metrics: { runs: 3, avg_cost_usd: 0.0021 },
      recent_traces: [{ trace_id: "trace-9f1e", model: "gpt-5.5", total_ms: 1234, cost_usd: 0.002, tool_calls: 2, errors: [] }],
      mcp: [{ name: "filesystem", transport: "stdio", state: "connected", tool_count: 14, last_error: null }, { name: "gmail", transport: "streamable_http", state: "disconnected", tool_count: 0, last_error: null }],
      mcp_user_sessions: [{ server: "gmail", subject: "101", state: "connected", last_used: Date.now() / 1000 }], scheduler: { enabled: true, due_now: 0 } })
    return json(res, 404, { detail: "not found" })
  }
  json(res, 404, { detail: "not found" })
})

server.listen(PORT, "127.0.0.1", () => console.log(`fake backend on http://127.0.0.1:${PORT}`))
