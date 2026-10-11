/**
 * A stand-in for the FastAPI backend used by the e2e suite.
 *
 * It speaks the same HTTP + SSE contract as `harness.api` (bearer JWT,
 * /ask/stream events, /approve, /upload, /healthz, /quality) and lets a test
 * inject every failure the real thing can produce, keyed by the question:
 *
 *   "APPROVAL …"   run pauses on a destructive tool → approval_required
 *   "ASK …"        run pauses on ask_user → approval_required with options
 *   "APPROVAL TWICE …"  as APPROVAL, but the approved run pauses again on a
 *                  stepped-up web_search (what a tainted run does)
 *   "DROP …"       stream some text, then close the socket without `done`
 *   "ERROR …"      stream an `error` event
 *   "SLOW …"       first token after 3 s (for the Stop button)
 *   "INJECT …"     security events: flagged tool result, stepped-up action, redacted answer
 *   "GMAIL …"      a Gmail search card (structured ui) then a send that pauses for approval
 *   "SHOPPING …"   the `lists` tool adds to Shopping -> a live checklist card
 *   "WEATHER …"    the `weather` tool -> a weather card
 *   "REPORT …" / "CHART …" / "LOCKED …"   create_file -> download card,
 *                  analyze_data -> chart + table, a Free user -> upgrade card
 *   "E500 / E429 / E401 / E422"   answer with that HTTP status, no stream
 *   "PAYWALL …" / "BROKE …" / "FULL …"   402 plan refusal (plan_required /
 *                  insufficient_balance / free_pool_exhausted)
 *   "HISTORY …"    reply states how many history turns arrived
 *   "LAUNCH …"     the launch_plan tool -> a launch plan card (plan id 900)
 *   "SALES …"      the business tool logs today -> a sales card; "FORECAST …" -> tomorrow's forecast card
 *   anything else  "Reply to: <question>" with one search_docs tool call
 *
 * Every reply also names the caller (`user=<sub>`) so isolation between
 * concurrent users is observable. `POST /__control {"down": true}` makes
 * /healthz fail; `GET /__state` exposes counters for assertions.
 */
import http from "node:http"
import crypto from "node:crypto"
import fs from "node:fs"

const PORT = Number(process.env.FAKE_BACKEND_PORT ?? 8765)
const SECRET = process.env.FASTAPI_JWT_SECRET ?? "e2e-service-secret"

// FAKE_TRAILER=1 (the walkthrough video, tests/trailer): natural messages pick the canned replies, so the
// recording shows what an owner would type instead of the SALES / FORECAST test prefixes. Off in the e2e suite.
const TRAILER_ALIASES = [
  [/16,?400/, "SALES"], [/kal|tomorrow/i, "FORECAST"], [/post|poster/i, "BRANDPOST"], [/open|start a|cloud kitchen/i, "LAUNCH"],
]
function trailerAlias(q) {
  if (!process.env.FAKE_TRAILER) return q
  const hit = TRAILER_ALIASES.find(([rx]) => rx.test(q))
  return hit ? `${hit[1]} ${q}` : q
}

const state = { down: false, approves: {}, executed: {}, uploads: [], asks: [], inFlight: {}, memory: {}, episodes: {}, conversations: {}, convMessages: {}, adminCalls: [], evalRuns: {}, prefs: {}, tasks: {}, google: {}, checkouts: [], todos: {}, reminders: {}, notes: {}, deviceTz: {}, transcripts: [], transcribed: [], spoken: [], apps: {}, billing: {}, churn: [], today: {}, whatsapp: {}, checkins: {}, kept: {}, linkDecisions: {}, brands: {}, brandSlots: {}, brandAssets: {}, brandPosts: {}, brandFiles: [], waitlist: [], waitlistBase: 0, launch: {}, launchAccess: {}, business: {}, businessPlan: {}, missions: {}, missionTrust: {}, missionPlan: {}, promises: {}, promiseAsking: {}, promisePlan: {}, promiseEmailOn: {}, customers: {} }


// ---- How's business: the real overview (business-fixture.json, from harness.sales via make_fixtures.py),
//      trimmed per plan exactly as sales/service.overview does, with the week recomputed from the days
const BUSINESS_FIXTURE = JSON.parse(fs.readFileSync(new URL("./business-fixture.json", import.meta.url), "utf8"))
function businessAccess(plan) {
  return { plan, forecast: plan !== "free", reasons: plan === "pro", ideas: plan === "pro" ? "all" : plan === "plus" ? "weekly" : "none", whatsapp: plan === "pro" }
}
function newBusiness(b, seeded) {
  const fx = BUSINESS_FIXTURE.overview
  return { business: { ...fx.business, id: 1, name: String(b.name ?? "My business"), kind: b.kind ?? "cafe", city: b.city ?? "",
                       brand_id: b.brand_id ?? null, launch_plan_id: b.launch_plan_id ?? null, paused: false },
           days: seeded ? fx.days.map((x) => ({ ...x })) : [], ideasUsed: 0 }
}
function businessOverview(b, plan) {
  const fx = structuredClone(BUSINESS_FIXTURE.overview)
  const today = fx.today
  const monday = new Date(today + "T12:00:00"); monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7))
  const ws = monday.toLocaleDateString("en-CA")
  const lastWs = new Date(monday); lastWs.setDate(lastWs.getDate() - 7)
  const lastSame = new Date(today + "T12:00:00"); lastSame.setDate(lastSame.getDate() - 7)
  const inWeek = b.days.filter((x) => x.day >= ws && x.day <= today && !x.closed)
  const lastWeek = b.days.filter((x) => x.day >= lastWs.toLocaleDateString("en-CA") && x.day <= lastSame.toLocaleDateString("en-CA") && !x.closed)
  const total = inWeek.reduce((s, x) => s + x.sales, 0), prev = lastWeek.reduce((s, x) => s + x.sales, 0)
  const ov = { ...fx, business: b.business, access: businessAccess(plan), days: b.days.slice(-90), logged_today: b.days.some((x) => x.day === today),
    week: { total: Math.round(total), days: inWeek.length, bills: inWeek.reduce((s, x) => s + (x.bills ?? 0), 0),
            last_week_same_days: lastWeek.length ? Math.round(prev) : null, change: lastWeek.length && prev > 0 ? Math.round((total / prev - 1) * 1000) / 1000 : null,
            best: inWeek.length ? inWeek.reduce((a, x) => (x.sales > a.sales ? x : a)).day : null },
    plan: b.business.launch_plan_id ? fx.plan : {}, locked: [], ideas_left: null }
  const logged = b.days.filter((x) => !x.closed).length
  if (logged < 14) {
    ov.forecast = { status: "learning", days_logged: logged, days_needed: 14 - logged }
    ov.slow = null; ov.ideas = []; ov.expected = []
  }
  if (plan === "free") {
    ov.forecast = { status: ov.forecast.status, days_logged: logged, days_needed: Math.max(0, 14 - logged) }
    ov.slow = null; ov.ideas = []; ov.expected = []
    ov.locked.push({ feature: "Tomorrow's sales forecast", plan: "plus" })
  } else if (plan === "plus" && ov.forecast.status === "ready") {
    if (ov.forecast.reasons?.length) ov.locked.push({ feature: "Why tomorrow looks this way", plan: "pro" })
    ov.forecast.reasons = []
    ov.ideas_left = Math.max(0, 1 - (b.ideasUsed ?? 0))
    ov.ideas = ov.ideas_left > 0 || b.ideasUsed ? ov.ideas.slice(0, 1) : []
    if (fx.ideas.length > ov.ideas.length) ov.locked.push({ feature: "An idea for every slow day", plan: "pro" })
  }
  return ov
}

// ---- launch plans: the real templates (launch-fixture.json, generated from harness.launch:
//   .venv/bin/python -c "import json; from harness.launch import kinds, plan; ..." -- see the fixture's _note)
//   and the same arithmetic as harness/launch/economics.py
const LAUNCH_FIXTURE = JSON.parse(fs.readFileSync(new URL("./launch-fixture.json", import.meta.url), "utf8"))
const LAUNCH_KINDS = LAUNCH_FIXTURE.kinds
function newLaunchPlan(id, b, live) {
  const t = structuredClone(LAUNCH_FIXTURE.plans[b.kind] ?? LAUNCH_FIXTURE.plans.cafe)
  const renting = b.renting ?? "yes"
  const RENT_KEYS = new Set(["rent", "deposit", "fitout", "warehouse"])
  for (const it of t.items) if (RENT_KEYS.has(it.key)) it.include = renting === "yes"
  const label = LAUNCH_KINDS.find((k) => k.key === b.kind)?.label ?? "Business"
  const now = new Date().toISOString()
  const searchable = t.items.filter((x) => x.search && x.include).length
  return { ...t, id, active: true, reads: 0, kind: b.kind, city: String(b.city).trim(), area: String(b.area ?? "").trim(),
    title: `${label} in ${[b.area, b.city].map((x) => String(x ?? "").trim()).filter(Boolean).join(", ")}`, conversation_id: null,
    answers: { size: b.size, renting, budget: b.budget ?? null, start: b.start ?? "", note: "" },
    status: live ? "sourcing" : "ready", error: "", sourced: live,
    progress: live ? { stage: "prices", done: Math.min(6, searchable), total: searchable } : {}, refreshes: 0, created_at: now, updated_at: now }
}
function launchSourced(p) {
  // the espresso machine (or the first item with a search) gets a checked seller; a benchmark and a supplier are found
  const it = p.items.find((x) => x.key === "espresso") ?? p.items.find((x) => x.search)
  const mine = it.status === "user"
  Object.assign(it, { status: mine ? "user" : "sourced", low: 145000, high: 210000, typical: 177500,
    sellers: [{ seller: "Coffee Kit India", price: 145000, url: "https://shop.example/espresso", quote: "Rs. 1,45,000" },
              { seller: "Brew Supply Co", price: 210000, url: "https://shop.example/espresso-2", quote: "₹2,10,000" }],
    checked_at: new Date().toISOString(), ...(mine ? {} : { amount: 177500 }) })
  p.benchmarks[0] = { ...p.benchmarks[0], value: "28-32%", status: "sourced", source: { url: "https://report.example/cafes", title: "Café report" } }
  p.suppliers = [{ query: "coffee machine dealer", near: p.city, search_link: "https://www.google.com/maps/search/?api=1&query=coffee",
    places: [{ name: "Valley Coffee Supplies", address: `Valley Coffee Supplies, Residency Road, ${p.city}, India` }] }]
  Object.assign(p, { status: "ready", progress: { stage: "done", done: 1, total: 1 } })
}
function launchView(p) {
  const a = p.assumptions
  let oneOff = 0, fixed = 0
  const byCat = {}
  for (const it of p.items) {
    const t = it.include ? it.amount * it.qty : 0
    if (it.monthly) fixed += t; else oneOff += t
    byCat[it.category] = (byCat[it.category] ?? 0) + t
  }
  const v = Math.min(0.99, a.variable.reduce((s, x) => s + x.pct, 0))
  const month = (price, units) => {
    const revenue = price * units * a.days_per_month, per = price * (1 - v), profit = per * units * a.days_per_month - fixed
    return { revenue: Math.round(revenue), variable_costs: Math.round(revenue * v), contribution_per_sale: per, fixed: Math.round(fixed),
      profit: Math.round(profit), margin: revenue ? profit / revenue : null, units_per_day: units,
      breakeven_per_day: per > 0 ? Math.ceil(fixed / per / a.days_per_month) : null }
  }
  const likely = month(a.price, a.units_per_day)
  const wc = fixed * a.working_capital_months, startup = oneOff + wc
  const pay = (m) => (m.profit > 0 ? Math.round((startup / m.profit) * 10) / 10 : null)
  const scen = { worst: month(a.price * 0.95, a.units_per_day * 0.7), likely, best: month(a.price, a.units_per_day * 1.3) }
  for (const m of Object.values(scen)) m.payback_months = pay(m)
  const top = Math.max(a.units_per_day * 1.5, (likely.breakeven_per_day ?? 0) * 2, 10)
  const chart = Array.from({ length: 13 }, (_, i) => {
    const u = (top * i) / 12, rev = a.price * u * a.days_per_month
    return { units_per_day: Math.round(u * 10) / 10, revenue: Math.round(rev), costs: Math.round(fixed + rev * v) }
  })
  const budget = p.answers.budget
  const { reads: _r, active: _a, ...rest } = p
  return { ...rest, economics: { ...likely, price: a.price, days_per_month: a.days_per_month, variable_share: v, one_off: Math.round(oneOff),
    working_capital: Math.round(wc), working_capital_months: a.working_capital_months, startup_total: Math.round(startup),
    payback_months: pay(likely), budget: budget ?? null, budget_gap: budget ? Math.round(budget - startup) : null, by_category: byCat,
    scenarios: scen, chart } }
}

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
    // not in the caller's plan: the picker shows it locked (harness.billing)
    { id: "fake-frontier", label: "Fake Frontier", input_usd_per_m: 10, output_usd_per_m: 50,
      supports_reasoning: true, efforts: ["low", "medium"], default_effort: "medium", locked: true, plan_needed: "pro" },
  ],
  plan: "free",
}

// The 402 body harness.billing.entitlements raises: detail is an object.
const PAYWALLS = {
  PAYWALL: { detail: "Fake Frontier needs the Plus plan.", code: "plan_required", plan_needed: "plus" },
  BROKE: { detail: "You've used this period's allowance. Upgrade or buy credits to continue.", code: "insufficient_balance", plan_needed: "plus" },
  FULL: { detail: "Free capacity is full for this month. Upgrade or buy credits to keep going.", code: "free_pool_exhausted", plan_needed: "plus" },
}

async function askStream(req, res, user) {
  const body = JSON.parse((await readBody(req)).toString() || "{}")
  const q = trailerAlias(String(body.question ?? ""))
  const history = Array.isArray(body.history) ? body.history : []
  state.asks.push({ user: user.sub, question: q, history: history.length, conversation_id: body.conversation_id ?? null,
                    docs_only: body.docs_only === true, connectors: body.connectors ?? [], mode: body.mode ?? "default",
                    model: body.model ?? null, effort: body.effort ?? null, client_timezone: body.client_timezone ?? null, connectors_auto: body.connectors_auto === true,
                    brand_id: body.brand_id ?? null })

  const pw = q.match(/^(PAYWALL|BROKE|FULL)\b/)
  if (pw) return json(res, 402, { detail: PAYWALLS[pw[1]] }, { "X-Reason": PAYWALLS[pw[1]].code })

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
    // like bind_settings: each turn's model / effort become the conversation's
    if (body.model !== undefined) { convRow.model = body.model ?? null; convRow.effort = body.effort ?? null }
  } else {
    convRow = newConversation(user, {
      model: body.model ?? null, effort: body.effort ?? null,
      connectors: Array.isArray(body.connectors) ? body.connectors : [],
      mode: body.mode ?? "default", docs_only: body.docs_only === true,
    })
  }
  if (!convRow.title) convRow.title = String(body.question ?? "").slice(0, 200)     // what was typed (not a trailer alias)
  // like ask.resolve_brand: asked for (0 = none), else the chat's, else one the message names
  const myBrands = (state.brands[user.sub] ?? []).filter((b) => !b.paused)
  if (typeof body.brand_id === "number") convRow.brand_id = body.brand_id || null
  else if (!convRow.brand_id && body.connectors_auto) {
    convRow.brand_id = myBrands.find((b) => q.toLowerCase().includes(b.name.toLowerCase()))?.id ?? null
  }
  const runBrand = myBrands.find((b) => b.id === convRow.brand_id) ?? null
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
    const payload = event === "done"
      ? { ...data, conversation_id: convRow.id, brand_id: runBrand?.id ?? null, brand_name: runBrand?.name ?? null }
      : event === "approval_required" ? { ...data, conversation_id: convRow.id } : data
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

    if (q.startsWith("SHOPPING")) {
      const items = (state.todos[user.sub] ??= [])
      for (const text of ["milk", "eggs"]) items.push({ id: items.length + 1, list_name: "Shopping", text, done: false })
      send("tool_call", { id: "c1", name: "lists", arguments: { action: "add", list: "Shopping", items: ["milk", "eggs"] }, step: 1 })
      send("tool_result", { id: "c1", name: "lists", ok: true, preview: "Added 2 item(s) to Shopping.", ms: 8, cached: false,
        ui: { kind: "todo_list", list: "Shopping", items } })
      send("text_start", { block }); send("text_delta", { block, text: "Added milk and eggs to your Shopping list." }); send("text_end", { block })
      send("done", { steps: 1, run_id: runId, cost_usd: 0.001, tools_used: ["lists"] })
      return res.end()
    }

    if (q.startsWith("WEATHER")) {
      send("tool_call", { id: "c1", name: "weather", arguments: { location: "Pune" }, step: 1 })
      send("tool_result", { id: "c1", name: "weather", ok: true, preview: "Pune now: Light rain", ms: 40, cached: false,
        ui: { kind: "weather", place: "Pune, Maharashtra, India",
              current: { temp: 27.4, feels: 29, humidity: 70, wind: 12, label: "Light rain", icon: "cloud-rain" },
              daily: [{ date: "2026-10-02", label: "Light rain", icon: "cloud-rain", max: 29, min: 22, rain_chance: 80 },
                      { date: "2026-10-03", label: "Clear sky", icon: "sun", max: 31, min: 23, rain_chance: 5 }] } })
      send("text_start", { block }); send("text_delta", { block, text: "Take an umbrella today." }); send("text_end", { block })
      send("done", { steps: 1, run_id: runId, cost_usd: 0.001, tools_used: ["weather"] })
      return res.end()
    }

    // Google Meet: "MEET link" (instant), "MEET event" (calendar invite with a Meet link), "MEET calls", "MEET transcript"
    if (q.startsWith("MEET ")) {
      const what = q.split(" ")[1]
      const link = "https://meet.google.com/abc-defg-hij"
      const tool = { link: "meet__create_meeting", event: "calendar__create_event", calls: "meet__recent_meetings", transcript: "meet__get_transcript" }[what]
      const ui = what === "link" ? { kind: "meet_link", uri: link, code: "abc-defg-hij" }
        : what === "event" ? { kind: "calendar_events", created: true, events: [{ id: "ev9", summary: "Call with Priya", start: "2026-10-09T10:00:00+05:30",
                               end: "2026-10-09T10:30:00+05:30", meet: link, link: "https://calendar.google.com/ev9" }] }
        : what === "calls" ? { kind: "meet_meetings", meetings: [{ id: "r1", code: "abc-defg-hij", start: "2026-10-07T09:00:00Z", end: "2026-10-07T09:42:00Z",
                               minutes: 42, participants: ["Guest", "Rahul"], transcript: true }] }
        : { kind: "meet_transcript", id: "r1", start: "2026-10-07T09:00:00Z", minutes: 42, participants: ["Guest", "Rahul"],
            doc: "https://docs.google.com/document/d/x",
            lines: Array.from({ length: 10 }, (_, i) => ({ who: i % 2 ? "Guest" : "Rahul", text: i ? `Line ${i}` : "I'll send the quote by Friday." })) }
      send("tool_call", { id: "c1", name: tool, arguments: {}, step: 1 })
      send("tool_result", { id: "c1", name: tool, ok: true, preview: "done", ms: 30, cached: false, ui })
      send("text_start", { block }); send("text_delta", { block, text: "Done." }); send("text_end", { block })
      send("done", { steps: 1, run_id: runId, cost_usd: 0.001, tools_used: [tool] })
      return res.end()
    }

    if (q.startsWith("IMAGE") || q.startsWith("ROUTE") || q.startsWith("GITHUB")) {
      const kind = q.split(" ")[0]
      const tool = { IMAGE: "generate_image", ROUTE: "travel_time", GITHUB: "github__my_work" }[kind]
      const ui = kind === "IMAGE" ? { kind: "image", name: "where-my-money-went.png", prompt: "A robot with an umbrella", size: "1024x1024" }
        : kind === "ROUTE" ? { kind: "route", origin: "Shaniwarwada", destination: "Pune Junction", mode: "foot", minutes: 35, km: 2.6,
                               link: "https://www.google.com/maps/dir/?api=1&origin=Shaniwarwada&destination=Pune+Junction&travelmode=walking" }
        : { kind: "issues", items: [{ repo: "acme/app", number: 12, title: "Fix login", state: "open", url: "https://github.com/acme/app/pull/12", pr: true, updated: "2026-10-01" }] }
      send("tool_call", { id: "c1", name: tool, arguments: {}, step: 1 })
      send("tool_result", { id: "c1", name: tool, ok: true, preview: "done", ms: 30, cached: false, ui })
      send("text_start", { block }); send("text_delta", { block, text: "Done." }); send("text_end", { block })
      send("done", { steps: 1, run_id: runId, cost_usd: 0.001, tools_used: [tool] })
      return res.end()
    }

    if (q.startsWith("BRANDPOST") || q.startsWith("BRANDSETUP")) {
      const setup = q.startsWith("BRANDSETUP")
      const tool = setup ? "brands" : "finish_image"
      const ui = setup
        ? { kind: "brand_setup", sentence: "a cosy café", suggestion: { kind: "cafe", label: "Café", name: "Chinar Café", looks: BRAND_LOOKS } }
        : { kind: "brand_set", brand: runBrand?.name ?? "", source: "kahwa.jpg", files: [
            { name: "chinar-cafe-post-kahwa.jpg", size: "post", width: 1080, height: 1080, label: "Instagram / Facebook post" },
            { name: "chinar-cafe-story-kahwa.jpg", size: "story", width: 1080, height: 1920, label: "Story / WhatsApp status" }] }
      send("tool_call", { id: "c1", name: tool, arguments: { image: "kahwa.jpg", headline: "Kahwa ₹80" }, step: 1 })
      send("tool_result", { id: "c1", name: tool, ok: true, preview: "done", ms: 30, cached: false, ui })
      send("text_start", { block }); send("text_delta", { block, text: setup ? "Pick a look." : "Here's your post." }); send("text_end", { block })
      send("done", { steps: 1, run_id: runId, cost_usd: 0.0, tools_used: [tool] })
      return res.end()
    }

    if (q.startsWith("LAUNCH")) {
      const ui = { kind: "launch_plan", id: 900, title: "Café in Srinagar", status: "sourcing", sourced: true, unit: "bill",
        startup_total: 1450000, profit: 82000, breakeven_per_day: 41, payback_months: 17.7, items: 22, url: "/launch/900",
        access: { allowed: true, reason: null, detail: "", plan_needed: null } }
      send("tool_call", { id: "c1", name: "launch_plan", arguments: { action: "start", kind: "cafe", city: "Srinagar", size: "small" }, step: 1 })
      send("tool_result", { id: "c1", name: "launch_plan", ok: true, preview: "done", ms: 30, cached: false, ui })
      send("text_start", { block }); send("text_delta", { block, text: "Your plan is on its way." }); send("text_end", { block })
      send("done", { steps: 1, run_id: runId, cost_usd: 0.0, tools_used: ["launch_plan"] })
      return res.end()
    }

    if (q.startsWith("SALES") || q.startsWith("FORECAST")) {
      const ov = BUSINESS_FIXTURE.overview
      const ui = q.startsWith("SALES")
        ? { kind: "sales_logged", business: ov.business.name, business_id: 1, day: ov.today, sales: 16400, bills: 52, closed: false,
            breakeven: ov.plan.breakeven, week: { total: ov.week.total + 16400, days: ov.week.days + 1, change: 0.06 }, url: "/business" }
        : { kind: "sales_forecast", business: ov.business.name, business_id: 1, tomorrow: ov.tomorrow, forecast: ov.forecast, slow: ov.slow,
            ideas: ov.ideas, locked: [], access: ov.access, url: "/business" }
      send("tool_call", { id: "c1", name: "business", arguments: { action: q.startsWith("SALES") ? "log" : "forecast" }, step: 1 })
      send("tool_result", { id: "c1", name: "business", ok: true, preview: "done", ms: 30, cached: false, ui })
      send("text_start", { block }); send("text_delta", { block, text: q.startsWith("SALES") ? "Logged ₹16,400 · 52 bills for today." : "Tomorrow looks slow." }); send("text_end", { block })
      send("done", { steps: 1, run_id: runId, cost_usd: 0.0, tools_used: ["business"] })
      return res.end()
    }

    if (q.startsWith("REPORT") || q.startsWith("CHART") || q.startsWith("LOCKED")) {
      const kind = q.split(" ")[0]
      const name = kind === "REPORT" ? "monthly-budget.pdf" : "where-my-money-went.png"
      const tool = kind === "CHART" ? "analyze_data" : "create_file"
      const ui = kind === "REPORT" ? { kind: "file", name, format: "pdf", size: 18_531, title: "Monthly budget" }
        : kind === "CHART" ? { kind: "chart", name, title: "Where my money went", rows: [["Category", "sum_Amount"], ["Housing", 30000], ["Food", 3150]] }
        : { kind: "upgrade", feature: "Creating files (PDF, Word, Excel, slides)", plan: "plus", plan_label: "Plus" }
      send("tool_call", { id: "c1", name: tool, arguments: { title: "Monthly budget" }, step: 1 })
      send("tool_result", { id: "c1", name: tool, ok: true, preview: "done", ms: 30, cached: false, ui })
      send("text_start", { block }); send("text_delta", { block, text: kind === "LOCKED" ? "That needs Plus." : "Here it is." }); send("text_end", { block })
      send("done", { steps: 1, run_id: runId, cost_usd: 0.001, tools_used: [tool] })
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
      state.approves[runId] = { user: user.sub, pending: true, repause: q.startsWith("APPROVAL TWICE"), ask: q.startsWith("ASK") }
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
    // "auto" stands in for the backend's choice, like providers/router.py
    send("done", { steps: 2, run_id: runId, cost_usd: 0.0021, tools_used: ["search_docs"],
                   model: !body.model || body.model === "auto" ? "gpt-5.6-luna" : body.model })
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
  if (a.repause && body.decision === "approve") {
    // The resumed run parks again, under the same run id, like /approve does.
    a.repause = false
    a.pending = true
    return json(res, 200, { answer: "The agent wants to run 'web_search'. Your approval is needed.", run_id: body.approval_id,
      prompt_version: "v", steps: 3, stopped_reason: "pending_approval", cached: false,
      pending_tool: { name: "web_search", arguments: { query: "latest AI news" }, tool_call_id: "c2" },
      security_events: [{ layer: "action", severity: "medium", source: "web_search", action: "stepped_up", reasons: ["context tainted by web_search; web_search needs your approval"], step: 3 }] })
  }
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
// the morning check-in (21-today / 28-hearth): a 3-morning streak so far; answering today makes it 4
const CHECKIN_REPLIES = { great: "Love that. Let's make the most of it.", ok: "Okay. I'll keep today simple.",
  tired: "Sorry to hear that. I'll keep today light.", busy: "Got it. I'll keep it short today." }
function checkinFor(sub) {
  const mood = state.checkins[sub] ?? null
  return { mood, reply: mood ? CHECKIN_REPLIES[mood] : null, streak: mood ? 4 : 3, week: [false, false, false, true, true, true, Boolean(mood)] }
}

/** The fake's Kept list: its waiting approvals and reminders, plus rows planted with POST /__kept. */
function keptFor(user) {
  const items = [
    ...Object.entries(state.approves).filter(([, a]) => a.user === user.sub && a.pending && !a.ask).map(([run_id, a]) => ({
      id: `approval:${run_id}`, kind: "approval", state: "needs_you", did: "Write notes.txt (waiting for you)", said: a.said ?? "Save my notes to a file",
      when: new Date().toISOString(), app: "File", conversation_id: a.conversation_id ?? "conv-kept", ref: { run_id, tool: "filesystem__write_file" } })),
    ...(state.reminders[user.sub] ?? []).filter((r) => r.status !== "cancelled").map((r) => ({
      id: `reminder:${r.id}`, kind: "reminder", state: r.status === "pending" ? "coming" : "done",
      did: r.status === "pending" ? `Reminder: ${r.text}` : `Reminded you: ${r.text}`, said: r.said ?? null, when: r.due_at, app: "Reminder",
      conversation_id: r.conversation_id ?? null, ref: { id: r.id, status: r.status } })),
    ...(state.kept[user.sub] ?? []),
    ...promisesOf(user.sub).filter((p) => p.status !== "dropped").map((p) => ({
      id: `promise:${p.id}`, kind: "promise", state: p.status === "open" ? "coming" : "done",
      did: p.status === "done" ? `Kept: ${p.what}` : p.direction === "mine" ? `You promised${p.who ? " " + p.who : ""}: ${p.what}` : `${p.who || "Someone"} promised you: ${p.what}`,
      said: p.quote || null, when: p.due_on ? `${p.due_on}T12:00:00Z` : p.created_at, app: "Promise", conversation_id: null,
      ref: { id: p.id, direction: p.direction, status: p.status, wrote_back: Boolean(p.last_contact_at), chased: Boolean(p.chased_at) } })),
  ]
  return items.sort((a, b) => String(a.when ?? "").localeCompare(String(b.when ?? "")))
}

/** Kept your word (harness.promises): the fake's promises, as /today and /kept show them. */
let promiseSeq = 900
function promisesOf(sub) { return (state.promises[sub] ??= []) }
function promiseRow(sub, p) {
  promiseSeq += 1
  const row = { id: promiseSeq, direction: p.direction, what: p.what, who: p.who ?? "", who_email: p.who_email ?? "",
    due_on: p.due_on ?? null, source: p.source ?? "chat", quote: p.quote ?? "", status: p.status ?? "open", thread_ref: "",
    last_contact_at: p.last_contact_at ?? null, chased_at: null, created_at: "2026-10-02T09:00:00Z", conversation_id: null, said: null }
  promisesOf(sub).push(row)
  return row
}
function promisedFor(sub) {
  const open = promisesOf(sub).filter((p) => p.status === "open")
  const mine = open.filter((p) => p.direction === "mine").map((p) => ({ ...p, overdue: Boolean(p.due_on) && p.due_on < "2026-10-02" }))
  const theirs = open.filter((p) => p.direction === "theirs")
    .map((p) => ({ ...p, late: !p.last_contact_at && !p.chased_at && Boolean(p.due_on) && p.due_on < "2026-10-02" }))
    .sort((a, b) => Number(b.late) - Number(a.late))
  return { mine: mine.slice(0, 5), theirs: theirs.slice(0, 5), counts: { mine: mine.length, theirs: theirs.length },
    asking: (state.promiseAsking[sub] ?? []).slice(0, 2) }
}
const promisePaid = (sub) => (state.promisePlan[sub] ?? "plus") !== "free"

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
const PNG_1X1 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
const BRAND_SIZE_LABELS = { post: "Instagram post 1:1", portrait: "Instagram feed 4:5", story: "Story · Reel cover · WhatsApp status",
  landscape: "Facebook · LinkedIn", x: "X (Twitter)", youtube: "YouTube thumbnail", pinterest: "Pinterest pin", a4: "A4 print" }

const BRAND_LOOKS = [
  { id: "cafe-warm", label: "Warm & cosy", font: "script", style: "warm natural light", voice: "friendly and playful",
    colors: [{ role: "primary", hex: "#B5502F" }, { role: "secondary", hex: "#F4EBDD" }, { role: "accent", hex: "#E0A458" }, { role: "text", hex: "#3B2A20" }] },
  { id: "cafe-minimal", label: "Modern minimal", font: "sans", style: "clean bright minimal", voice: "calm and confident",
    colors: [{ role: "primary", hex: "#1F1F1F" }, { role: "secondary", hex: "#F5F3EE" }, { role: "accent", hex: "#8BA888" }, { role: "text", hex: "#1F1F1F" }] },
  { id: "cafe-heritage", label: "Kashmiri heritage", font: "serif", style: "rich chinar reds and gold", voice: "warm and proud of tradition",
    colors: [{ role: "primary", hex: "#A8402C" }, { role: "secondary", hex: "#F3E6D3" }, { role: "accent", hex: "#C9A227" }, { role: "text", hex: "#2E1F18" }] },
]

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
  return { id, title, preview, model, effort, connectors, mode, docs_only, brand_id: row.brand_id ?? null, message_count: count, created_at, updated_at }
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
    state.google[String(b.user)] = { connected: true, products: Array.isArray(b.products) ? b.products : ["gmail", "calendar", "drive", "docs"], scopes: [],
      ...(typeof b.restricted === "boolean" ? { restricted: b.restricted } : {}) }
    return json(res, 200, { ok: true })
  }
  if (url.pathname === "/__state") return json(res, 200, state)
  // Test hook: plant a server-owned conversation (and optionally its transcript)
  // for a user, with a chosen timestamp -- what the rail reads.
  if (url.pathname === "/__apps" && req.method === "POST") {
    // {user, apps: {github: true}}: a work app connected before they were hidden
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    state.apps[b.user] = { ...(state.apps[b.user] ?? {}), ...(b.apps ?? {}) }
    return json(res, 200, { ok: true })
  }
  // POST /__customers {user, customers}: seed a user's list
  if (url.pathname === "/__customers" && req.method === "POST") {
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    state.customers[String(b.user)] = b.customers ?? []
    return json(res, 200, { ok: true })
  }
  if (url.pathname === "/__business" && req.method === "POST") {
    // {user, plan?: "free"|"plus"|"pro", seeded?: true}: the plan the overview is trimmed for, and a business with 100 days already
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    if (b.plan) state.businessPlan[b.user] = b.plan
    if (b.seeded) state.business[b.user] = newBusiness({ name: "Chinar Café", kind: "cafe", city: "Srinagar", brand_id: 200, launch_plan_id: 900 }, true)
    return json(res, 200, { ok: true })
  }
  if (url.pathname === "/__missions" && req.method === "POST") {
    // {user, waiting?: true, plan?: "plus"}: a slow-day mission waiting for the owner's go-ahead, and the plan (default Pro)
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    if (b.plan) state.missionPlan[b.user] = b.plan
    if (b.waiting) (state.missions[b.user] ??= []).push(fakeMission(700 + (state.missions[b.user]?.length ?? 0)))
    return json(res, 200, { ok: true })
  }
  if (url.pathname === "/__launch" && req.method === "POST") {
    // {user, access?: {allowed, reason, detail, plan_needed}}: whether live prices are allowed (default yes)
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    if (b.access) state.launchAccess[b.user] = b.access
    return json(res, 200, { ok: true })
  }
  if (url.pathname === "/__brands" && req.method === "POST") {
    // {user, slots?, brands?: [{name}]}: how many brands the user may have, and brands they already made
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    if (typeof b.slots === "number") state.brandSlots[b.user] = b.slots
    for (const [i, x] of (b.brands ?? []).entries()) {
      const look = BRAND_LOOKS[i % BRAND_LOOKS.length]
      ;(state.brands[b.user] ??= []).push({ id: 200 + i, name: x.name, kind: "cafe", look: look.id, colors: look.colors, style: look.style,
                                             voice: look.voice, font: look.font, logo: "", paused: false, active: true })
    }
    return json(res, 200, { ok: true })
  }
  if (url.pathname === "/__billing" && req.method === "POST") {
    // put a user on a paid plan for the cancel-flow tests; `extra` overrides any GET /billing field
    // (messages_left, nudge, trial_days, trialing… for 26-free-vs-paid.spec.ts)
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    const plan = b.plan ? { plan: b.plan, plan_label: b.plan[0].toUpperCase() + b.plan.slice(1), status: "active",
                            renews_at: "2026-11-03T00:00:00Z", ends_at: null } : {}
    state.billing[b.user] = { ...plan, ...(b.extra ?? {}) }
    return json(res, 200, { ok: true })
  }
  if (url.pathname === "/__whatsapp" && req.method === "POST") {
    // {user, enabled?, linked?}: switch WhatsApp on for a user, or pretend their code arrived from WhatsApp
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    state.whatsapp[b.user] = { ...(state.whatsapp[b.user] ?? {}), ...b }
    return json(res, 200, { ok: true })
  }
  if (url.pathname === "/__today" && req.method === "POST") {
    // extra GET /today fields for a user: leave_by, birthdays, tomorrow (21-today.spec.ts)
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    state.today[b.user] = b.extra ?? {}
    state.todaySlowMs = { ...(state.todaySlowMs ?? {}), [b.user]: b.slowMs ?? 0 }   // delay the full brief
    return json(res, 200, { ok: true })
  }
  if (url.pathname === "/__promises" && req.method === "POST") {
    // {user, promises?: [{direction, what, who, due_on…}], asking?: [{id, summary, people}], plan?: "free" | "plus"}
    // (37-promises.spec.ts)
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    for (const p of b.promises ?? []) promiseRow(b.user, p)
    if (b.asking) state.promiseAsking[b.user] = b.asking
    if (b.plan) state.promisePlan[b.user] = b.plan
    return json(res, 200, { ok: true })
  }
  if (url.pathname === "/__kept" && req.method === "POST") {
    // {user, items}: extra GET /kept rows (actions, tasks…) on top of the ones the
    // fake derives from its approvals and reminders (29-kept.spec.ts)
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    state.kept[b.user] = b.items ?? []
    return json(res, 200, { ok: true })
  }
  if (url.pathname === "/__onboarding" && req.method === "POST") {
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    state.prefs[b.user] = { ...(state.prefs[b.user] ?? {}), onboarded: false }
    return json(res, 200, { ok: true })
  }
  if (url.pathname === "/__transcripts" && req.method === "POST") {
    // what the next /voice/transcribe calls will "hear", in order
    state.transcripts.push(...(JSON.parse((await readBody(req)).toString() || "{}").texts ?? []))
    return json(res, 200, { ok: true })
  }
  if (url.pathname === "/__reminder" && req.method === "POST") {
    // plant a reminder that has already fired (what the scheduler would leave)
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    const rows = (state.reminders[b.user] ??= [])
    const r = { id: rows.length + 1, text: b.text, due_at: b.due_at ?? new Date().toISOString(), status: b.status ?? "sent", sent_at: null, said: b.said ?? null, conversation_id: b.conversation_id ?? null }
    rows.push(r)
    return json(res, 200, r)
  }
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
  if (url.pathname === "/__reset") { Object.assign(state, { down: false, approves: {}, executed: {}, uploads: [], asks: [], inFlight: {}, memory: {}, episodes: {}, conversations: {}, convMessages: {}, adminCalls: [], evalRuns: {}, prefs: {}, tasks: {}, google: {}, checkouts: [], todos: {}, reminders: {}, notes: {}, deviceTz: {}, transcripts: [], transcribed: [], spoken: [], apps: {}, billing: {}, churn: [], today: {}, whatsapp: {}, checkins: {}, kept: {}, linkDecisions: {}, brands: {}, brandSlots: {}, brandAssets: {}, brandPosts: {}, brandFiles: [], waitlist: [], waitlistBase: 0, launch: {}, launchAccess: {}, business: {}, businessPlan: {}, missions: {}, missionTrust: {}, missionPlan: {}, promises: {}, promiseAsking: {}, promisePlan: {}, promiseEmailOn: {}, customers: {} }); convSeq = 0; return json(res, 200, { ok: true }) }
  if (url.pathname === "/healthz") return state.down ? json(res, 503, { status: "down" }) : json(res, 200, { status: "ok" })
  // approve-by-link (30-approve-link): no JWT, the token is the credential. Tokens whose
  // first part starts "ok" are a waiting calendar event; anything else is invalid (410).
  const link = url.pathname.match(/^\/approval-links\/([^/]+)$/)
  if (link) {
    const token = link[1]
    if (!token.startsWith("ok")) return json(res, 410, { detail: "This link has expired or isn't valid." })
    const decided = state.linkDecisions[token]
    if (req.method === "GET") {
      return json(res, 200, decided ? { state: "decided", asked: "Find a slot", card: null, conversation_id: "conv-link" } : {
        state: "waiting", asked: "Find a free slot this afternoon and block it", conversation_id: "conv-link",
        card: { title: "Add an event to your calendar?", rows: [["Event", "Focus time"], ["When", "Tue 6 Oct, 5:15 PM – 5:30 PM"], ["Invites", "Nobody — only your calendar"]], body: "" } })
    }
    const { decision } = JSON.parse((await readBody(req)).toString() || "{}")
    if (decided) return json(res, 200, { state: "decided", answer: "" })
    state.linkDecisions[token] = decision
    return json(res, 200, { state: decision === "approve" ? "approved" : "rejected", answer: decision === "approve" ? "Added Focus time at 5:15 PM." : "Okay, I didn't add it.", waiting_again: false, conversation_id: "conv-link" })
  }
  // public homepage prices (28-hearth): India by device timezone, like billing.public_region
  // pre-registration (/join): public like /billing/prices. POST /__waitlist {base} pretends
  // that many people joined already, so the count can be shown.
  if (url.pathname === "/__waitlist" && req.method === "POST") {
    state.waitlistBase = Number(JSON.parse((await readBody(req)).toString() || "{}").base ?? 0)
    return json(res, 200, { ok: true })
  }
  if (url.pathname === "/waitlist/count") return json(res, 200, { total: state.waitlistBase + state.waitlist.length })
  if (url.pathname === "/waitlist" && req.method === "POST") {
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    const email = String(b.email ?? "").trim().toLowerCase()
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return json(res, 422, { detail: "That doesn't look like an email address." })
    if (!state.waitlist.some((w) => w.email === email)) state.waitlist.push({ email, trade: b.trade ?? "", city: b.city ?? "", persona: b.persona ?? "", interest: b.interest ?? "", source: b.source ?? "" })
    return json(res, 200, { ok: true, total: state.waitlistBase + state.waitlist.length })
  }
  if (url.pathname === "/billing/prices") {
    const india = ["Asia/Kolkata", "Asia/Calcutta"].includes(url.searchParams.get("tz") ?? "")
    const p = (label, amount) => ({ month: { amount, currency: india ? "INR" : "USD", label } })
    return json(res, 200, { region: india ? "in" : "intl", trial_days: 7, plans: [
      { id: "free", label: "Free", prices: p(india ? "₹0" : "$0", 0) },
      { id: "plus", label: "Plus", prices: p(india ? "₹499" : "$20", india ? 499 : 20) },
      { id: "pro", label: "Pro", prices: p(india ? "₹1,499" : "$100", india ? 1499 : 100) },
    ] })
  }
  if (url.pathname === "/connectors") return json(res, 200, [
    { key: "arxiv", label: "Research", description: "Search and read arXiv papers", kind: "builtin", icon: "book-2", per_user: false, auth: null, servers: [] },
    ...[["gmail", "Gmail", "mail"], ["calendar", "Google Calendar", "calendar"], ["drive", "Google Drive", "brand-google-drive"], ["docs", "Google Docs", "file-text"]]
      .map(([key, label, icon]) => ({ key, label, description: `${label} on your own Google account`, kind: "builtin", icon, per_user: true, auth: "google", product: key, group: "Google Workspace", servers: [],
        restricted: key === "gmail" || key === "drive" })),
    // GitHub, Notion and Slack are hidden from the catalogue (connectors/registry.WORK_APPS_HIDDEN)
  ])
  if (url.pathname === "/quality") return json(res, 200, { available: true, avg_correctness: 0.91, avg_faithfulness: 0.88, pass_rate: 0.9, cases: 20, gate_passed: true, blocking_failures: [], advisory_notes: [] })

  // ---- client review links (harness.brands.review): no account; the token is "review-<post id>.<anything>"
  const rv = url.pathname.match(/^\/review\/(review-[0-9]+\.[A-Za-z0-9_-]{20,})(\/files\/([^/]+))?$/)
  if (rv) {
    const post = Object.values(state.brandPosts).flat().find((x) => `review-${x.id}` === rv[1].split(".")[0] && x.active !== false)
    if (!post) return json(res, 410, { detail: "This review link has expired or isn't valid. Ask for a new one." })
    if (rv[3]) {
      if (!post.files.some((f) => f.name === decodeURIComponent(rv[3]))) return json(res, 404, { detail: "Not part of this post." })
      res.writeHead(200, { "Content-Type": "image/png" })
      return res.end(Buffer.from(PNG_1X1, "base64"))
    }
    const owner = Object.entries(state.brands).find(([, bs]) => bs.some((b) => b.id === post.brand_id))
    const b = owner?.[1].find((x) => x.id === post.brand_id)
    if (req.method === "GET") {
      return json(res, 200, { brand: b ? { name: b.name, colors: b.colors, font: b.font, logo: null, handle: b.handle ?? "" } : null,
                              post, expires_at: new Date(Date.now() + 14 * 864e5).toISOString() })
    }
    const d = JSON.parse((await readBody(req)).toString() || "{}")
    if (d.decision === "changes" && !String(d.comment ?? "").trim()) return json(res, 422, { detail: "Say what you'd like changed." })
    post.review_status = d.decision === "approve" ? "approved" : "changes"
    post.review_comment = (d.name ? `${d.name}: ` : "") + String(d.comment ?? "").trim()
    return json(res, 200, { status: post.review_status, comment: post.review_comment })
  }

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
  // ---- billing (harness.billing): a free plan with part of its allowance used
  if (url.pathname === "/billing" && req.method === "GET") {
    return json(res, 200, {
      enabled: true, plan: "free", plan_label: "Free", status: null, renews_at: null, ends_at: null,
      allowance_usd: 0.5, allowance_left_usd: 0.2, credits_usd: 1.5, has_portal: true,
      // billing/plans.RECOMMENDED, from the persona
      recommended_plan: ({ founder: "plus", developer: "pro", student: "plus", professional: "plus", personal: "plus" })[state.prefs[user.sub]?.persona] ?? null,
      plans: [
        { id: "free", label: "Free", price_usd_month: 0, model_tiers: ["basic"], max_effort: "medium", research_allowed: false, monthly_allowance_usd: 0.5, best_for: "Logging sales, reminders and your customer list, on WhatsApp too" },
        { id: "plus", label: "Plus", price_usd_month: 20, model_tiers: ["basic", "advanced"], max_effort: "xhigh", research_allowed: true, monthly_allowance_usd: 8, best_for: "A shop or small business: tomorrow's forecast, a slow day handled each week and posts in your brand" },
        { id: "pro", label: "Pro", price_usd_month: 100, model_tiers: ["basic", "advanced", "frontier"], max_effort: "xhigh", research_allowed: true, monthly_allowance_usd: 40, best_for: "Busy owners and several outlets: every slow day handled, up to 5 businesses and 3 brands" },
      ],
      ...(state.billing[user.sub] ?? {}),        // last, so a test can override any field, plans included
    })
  }
  if (url.pathname === "/billing/leave" && req.method === "POST") {
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    const acct = state.billing[user.sub] ?? {}
    if (!acct.plan || acct.plan === "free") return json(res, 409, { detail: "There's no paid plan to change." })
    const outcome = { keep: "kept", downgrade: "downgraded", cancel: "cancelled" }[b.action]
    state.churn.push({ user: user.sub, plan: acct.plan, reason: b.reason, detail: b.detail ?? "", outcome })
    if (b.action === "downgrade") Object.assign(acct, { plan: "plus", plan_label: "Plus" })
    if (b.action === "cancel") Object.assign(acct, { status: "cancelling", ends_at: acct.renews_at, renews_at: null })
    return json(res, 200, { outcome, plan: acct.plan, ends_at: acct.ends_at ?? null })
  }
  if (url.pathname === "/billing/resume" && req.method === "POST") {
    const acct = state.billing[user.sub] ?? {}
    Object.assign(acct, { status: "active", renews_at: acct.ends_at, ends_at: null })
    return json(res, 200, { plan: acct.plan, status: "active" })
  }
  if (url.pathname === "/billing/checkout" && req.method === "POST") {
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    if (!["plus", "pro", "topup"].includes(b.product)) return json(res, 422, { detail: "bad product" })
    state.checkouts.push({ user: user.sub, product: b.product, interval: b.interval ?? null })
    // stands in for the Dodo Payments hosted checkout URL
    return json(res, 200, { url: `/billing?checkout=${b.product}` })
  }
  if (url.pathname === "/billing/portal" && req.method === "POST") return json(res, 200, { url: "/billing?portal=1" })
  // ---- reminders, lists, notes (harness.api.routes.personal), per user
  if (url.pathname === "/reminders" && req.method === "GET") {
    const scope = url.searchParams.get("scope") ?? "upcoming"
    const want = scope === "due" ? ["sent"] : scope === "open" ? ["pending", "sent"] : ["pending"]
    return json(res, 200, (state.reminders[user.sub] ?? []).filter((r) => want.includes(r.status)))
  }
  const remOne = url.pathname.match(/^\/reminders\/(\d+)$/)
  if (remOne && req.method === "DELETE") {
    const r = (state.reminders[user.sub] ?? []).find((x) => x.id === Number(remOne[1]))
    if (!r) return json(res, 404, { detail: "No such reminder." })
    r.status = "cancelled"
    return json(res, 200, r)
  }
  const remDone = url.pathname.match(/^\/reminders\/(\d+)\/done$/)
  if (remDone && req.method === "POST") {
    const r = (state.reminders[user.sub] ?? []).find((x) => x.id === Number(remDone[1]))
    if (!r) return json(res, 404, { detail: "No such reminder." })
    r.status = "done"
    return json(res, 200, r)
  }
  if (url.pathname === "/lists" && req.method === "GET") {
    const lists = {}
    for (const it of state.todos[user.sub] ?? []) if (!it.done) (lists[it.list_name] ??= []).push(it)
    return json(res, 200, { lists })
  }
  if (url.pathname === "/lists" && req.method === "POST") {
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    const items = (state.todos[user.sub] ??= [])
    const it = { id: items.length + 1, list_name: b.list || "To-do", text: String(b.text ?? ""), done: false }
    items.push(it)
    return json(res, 200, it)
  }
  const item = url.pathname.match(/^\/lists\/items\/(\d+)$/)
  if (item && req.method === "PATCH") {
    const it = (state.todos[user.sub] ?? []).find((x) => x.id === Number(item[1]))
    if (!it) return json(res, 404, { detail: "No such item." })
    it.done = Boolean(JSON.parse((await readBody(req)).toString() || "{}").done)
    return json(res, 200, it)
  }
  // ---- downloads (harness.api.routes.files)
  if (url.pathname === "/files" && req.method === "GET") {
    return json(res, 200, [
      { name: "where-my-money-went.png", size: 48_000, modified: Date.now() / 1000, kind: "image" },
      { name: "monthly-budget.pdf", size: 18_531, modified: Date.now() / 1000 - 3600, kind: "document" },
    ])
  }
  const file = url.pathname.match(/^\/files\/([^/]+)$/)
  if (file && req.method === "GET") {
    const name = decodeURIComponent(file[1])
    if (name === "monthly-budget.pdf") {
      res.writeHead(200, { "Content-Type": "application/pdf", "Content-Disposition": `attachment; filename="${name}"` })
      return res.end(Buffer.from("%PDF-1.4 fake"))
    }
    if (name === "where-my-money-went.png") {
      // a real 1x1 PNG so the <img> loads
      res.writeHead(200, { "Content-Type": "image/png", "Content-Disposition": `inline; filename="${name}"` })
      return res.end(Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64"))
    }
    if (state.brandFiles.includes(name)) {
      res.writeHead(200, { "Content-Type": "image/png" })
      return res.end(Buffer.from(PNG_1X1, "base64"))
    }
    return json(res, 404, { detail: "No such file." })
  }
  // ---- voice (harness.api.routes.voice)
  if (url.pathname === "/voice/transcribe" && req.method === "POST") {
    const buf = await readBody(req)
    const seconds = Number((buf.toString("latin1").match(/name="seconds"\r\n\r\n([0-9.]+)/) ?? [])[1] ?? 0)
    state.transcribed.push({ user: user.sub, bytes: buf.length, seconds })
    return json(res, 200, { text: state.transcripts.shift() ?? "SHOPPING add milk and eggs" })
  }
  if (url.pathname === "/voice/speak" && req.method === "POST") {
    state.spoken.push(JSON.parse((await readBody(req)).toString() || "{}").text)
    res.writeHead(200, { "Content-Type": "audio/mpeg" })
    return res.end(Buffer.from("ID3fake"))          // undecodable on purpose: playback errors out instantly
  }
  if (url.pathname === "/settings/onboarded" && req.method === "POST") {
    state.prefs[user.sub] = { ...(state.prefs[user.sub] ?? {}), onboarded: true }
    return json(res, 200, { onboarded: true })
  }
  if (url.pathname === "/settings/timezone" && req.method === "POST") {
    state.deviceTz[user.sub] = JSON.parse((await readBody(req)).toString() || "{}").timezone
    return json(res, 200, { timezone: state.deviceTz[user.sub], timezone_auto: true })
  }
  // ---- Notifications (harness/push.py): off here; headless Chromium has no push service
  if (url.pathname === "/push" && req.method === "GET") return json(res, 200, { enabled: false, public_key: null, devices: 0, this_device: false })
  if (url.pathname.startsWith("/push/")) return json(res, 503, { detail: "Notifications aren't set up on this server yet." })
  // ---- WhatsApp linking (harness/whatsapp): off unless a test switches it on
  if (url.pathname === "/whatsapp/link") {
    const w = state.whatsapp[user.sub] ?? {}
    if (req.method === "GET") {
      if (!w.enabled) return json(res, 200, { enabled: false, linked: false })
      return json(res, 200, { enabled: true, linked: !!w.linked, phone: w.linked ? "+91 ••••• 3210" : null,
                              business_number: "+91 90000 00000", chat_link: w.linked ? "https://wa.me/919000000000" : null })
    }
    if (req.method === "POST") {
      if (!w.enabled) return json(res, 503, { detail: "WhatsApp isn't set up on this server yet." })
      state.whatsapp[user.sub] = { ...w, code: "482913" }
      return json(res, 200, { code: "482913", message: "HANGUL 482913", expires_in: 900, business_number: "+91 90000 00000",
                              wa_link: "https://wa.me/919000000000?text=HANGUL%20482913" })
    }
    if (req.method === "DELETE") {
      state.whatsapp[user.sub] = { ...w, linked: false }
      return json(res, 200, { unlinked: true })
    }
  }
  if (url.pathname === "/today/checkin" && req.method === "POST") {
    const mood = JSON.parse((await readBody(req)).toString() || "{}").mood
    if (!CHECKIN_REPLIES[mood]) return json(res, 422, { detail: "bad mood" })
    state.checkins[user.sub] = mood
    return json(res, 200, checkinFor(user.sub))
  }
  if (url.pathname === "/today" && req.method === "GET") {
    const p = state.prefs[user.sub] ?? {}
    const quick = url.searchParams.get("quick") === "1"
    const slow = state.todaySlowMs?.[user.sub] ?? 0
    if (!quick && slow) await new Promise((r) => setTimeout(r, slow))
    const brief = {
      greeting: "Good morning", name: (p.display_name || "Alice").split(" ")[0], date_label: "Thursday, 02 October",
      timezone: "Asia/Kolkata", city: p.city ?? "",
      weather: p.city ? { place: `${p.city}, India`, current: { temp: 27.4, label: "Light rain", icon: "cloud-rain" }, daily: [{ max: 29, min: 22, rain_chance: 80 }] } : null,
      events: state.google[user.sub] ? [{ summary: "Standup", start: "2026-10-02T10:00:00+05:30", end: "2026-10-02T10:15:00+05:30" }] : null,
      emails: state.google[user.sub] ? [{ id: "m1", from: "HDFC Bank <alerts@hdfc.example>", subject: "Statement ready" }] : null,
      reminders: (state.reminders[user.sub] ?? []).filter((r) => r.status !== "done"),
      todos: (state.todos[user.sub] ?? []).filter((t) => !t.done),
      approvals: Object.entries(state.approves).filter(([, a]) => a.user === user.sub && a.pending)
        .map(([run_id]) => ({ run_id, conversation_id: null, tool: "filesystem__write_file" })),
      connected: state.google[user.sub] ? ["gmail", "calendar"] : [],
      tomorrow: null, leave_by: null, birthdays: null,
      checkin: checkinFor(user.sub),
      memory: (() => { const m = memoryFor(user).find((x) => x.active); return m ? { id: m.id, content: m.content, kind: m.kind } : null })(),
      suggestion: { kind: "brief", learned: true, count: 5, line: "You usually ask me this between 5am and 10am. Shall I?",
        chips: [{ label: "Brief me", prompt: "Give me my brief for today." }, { label: "Weather", prompt: "What's the weather like today?" }] },
      promises: promisedFor(user.sub),
      ...(state.today[user.sub] ?? {}),
      partial: false,
    }
    // quick=1: only what the database knows; Google, weather and maps parts are still to come
    return json(res, 200, quick ? { ...brief, weather: null, events: null, emails: null, replies: null, birthdays: null,
      leave_by: null, tomorrow: null, connected: [], partial: true } : brief)
  }
  if (url.pathname === "/notes" && req.method === "GET") return json(res, 200, state.notes[user.sub] ?? [])
  // ---- Kept your word (harness.api.routes.promises)
  if (url.pathname.startsWith("/promises")) {
    const mine = promisesOf(user.sub)
    const body = req.method === "GET" ? {} : JSON.parse((await readBody(req)).toString() || "{}")
    if (url.pathname === "/promises" && req.method === "GET") {
      const status = url.searchParams.get("status") ?? "open"
      const paid = promisePaid(user.sub)
      return json(res, 200, { promises: mine.filter((p) => status === "all" || p.status === status), counts: promisedFor(user.sub).counts,
        access: { plan: paid ? "plus" : "free", email: paid, meetings: paid, chase: paid },
        email_on: state.promiseEmailOn[user.sub] ?? true, asking: state.promiseAsking[user.sub] ?? [] })
    }
    if (url.pathname === "/promises" && req.method === "POST") return json(res, 200, promiseRow(user.sub, body))
    if (url.pathname === "/promises/settings" && req.method === "PUT") {
      state.promiseEmailOn[user.sub] = Boolean(body.email_on)
      return json(res, 200, { email_on: Boolean(body.email_on) })
    }
    if (url.pathname === "/promises/capture" && req.method === "POST") {
      if (!promisePaid(user.sub)) return json(res, 402, { detail: { detail: "Keeping track of what was promised in meetings is part of Plus.", code: "plan_required", plan_needed: "plus" } }, { "X-Reason": "plan_required" })
      // the fake "model": each clause is a promise; "I'll …" is the user's, "<Name> will …" someone else's
      const asked = (state.promiseAsking[user.sub] ?? []).find((a) => a.id === body.meeting_id)
      const found = String(body.text).split(/,| and /).map((s) => s.trim()).filter(Boolean).map((s) => {
        const theirs = s.match(/^([A-Z][a-z]+) (?:will|shares?|sends?) (.+)$/)
        return theirs ? promiseRow(user.sub, { direction: "theirs", who: theirs[1], what: theirs[2][0].toUpperCase() + theirs[2].slice(1), source: "meeting", quote: s })
          : /^I'?ll /i.test(s) ? promiseRow(user.sub, { direction: "mine", who: asked?.people?.[0]?.name ?? "", what: s.replace(/^I'?ll /i, "").replace(/^\w/, (c) => c.toUpperCase()), source: "meeting", quote: s })
          : null
      }).filter(Boolean)
      state.promiseAsking[user.sub] = (state.promiseAsking[user.sub] ?? []).filter((a) => a.id !== body.meeting_id)
      return json(res, 200, { promises: found })
    }
    const skip = url.pathname.match(/^\/promises\/meetings\/([\w-]+)\/skip$/)
    if (skip && req.method === "POST") {
      state.promiseAsking[user.sub] = (state.promiseAsking[user.sub] ?? []).filter((a) => a.id !== skip[1])
      return json(res, 200, { ok: true })
    }
    const r = url.pathname.match(/^\/promises\/(\d+)(?:\/(chase))?$/)
    const p = r && mine.find((x) => x.id === Number(r[1]))
    if (!p) return json(res, 404, { detail: "No such promise." })
    if (r[2] === "chase" && req.method === "POST") {
      if (!promisePaid(user.sub)) return json(res, 402, { detail: { detail: "Chasing promises is part of Plus.", code: "plan_required", plan_needed: "plus" } }, { "X-Reason": "plan_required" })
      p.chased_at = "2026-10-02T10:00:00Z"
      return json(res, 200, { prompt: `PROMISECHASE Draft a short, polite follow-up email to ${p.who} about what they promised: "${p.what}".` })
    }
    if (req.method === "PATCH") {
      if (body.status) p.status = body.status
      if (body.what) p.what = body.what
      if (body.clear_due) p.due_on = null
      else if (body.due_on) p.due_on = body.due_on
      return json(res, 200, p)
    }
  }
  // ---- the Kept tab (harness.api.routes.kept)
  if (url.pathname === "/kept/count" && req.method === "GET") return json(res, 200, { needs_you: keptFor(user).filter((i) => i.state === "needs_you").length })
  if (url.pathname === "/kept" && req.method === "GET") {
    const q = (url.searchParams.get("q") ?? "").trim().toLowerCase()
    let items = keptFor(user)
    if (q) {
      const words = q.split(/\s+/).filter((w) => w.length > 2 && !["what", "did", "ask", "about", "the"].includes(w))
      const held = [
        ...(state.todos[user.sub] ?? []).map((t) => ({ id: `todo:${t.id}`, kind: "todo", state: t.done ? "done" : "kept", did: `On ${t.list_name}: ${t.text}`, said: null, when: null, app: "List", conversation_id: null, ref: { id: t.id, list: t.list_name, done: t.done } })),
        ...(state.notes[user.sub] ?? []).map((n) => ({ id: `note:${n.id}`, kind: "note", state: "kept", did: `Note: ${n.text}`, said: null, when: n.created_at, app: "Note", conversation_id: null, ref: { id: n.id } })),
        ...memoryFor(user).filter((m) => m.active).map((m) => ({ id: `memory:${m.id}`, kind: "memory", state: "kept", did: `Remembered: ${m.content}`, said: null, when: null, app: "Memory", conversation_id: null, ref: { id: m.id } })),
      ]
      items = [...items, ...held].filter((i) => words.some((w) => `${i.said ?? ""} ${i.did}`.toLowerCase().includes(w)))
    }
    const lists = {}
    for (const t of state.todos[user.sub] ?? []) if (!t.done) lists[t.list_name] = (lists[t.list_name] ?? 0) + 1
    return json(res, 200, { now: new Date().toISOString(), query: q || null, items, needs_you: items.filter((i) => i.state === "needs_you").length,
      holding: { lists, notes: (state.notes[user.sub] ?? []).length, memories: memoryFor(user).filter((m) => m.active).length, files: 2 } })
  }
  // ---- personalisation, scheduled tasks, integrations (per user)
  // ---- Missions (harness.missions): slow days Hangul carries through
  if (url.pathname.startsWith("/missions")) {
    const mine = state.missions[user.sub] ??= []
    const allowed = ["plus", "pro"].includes(state.missionPlan[user.sub] ?? "pro")
    if (url.pathname === "/missions" && req.method === "GET") {
      return json(res, 200, { allowed, missions: [...mine].reverse(), trust: state.missionTrust[user.sub] ?? [],
        this_month: missionReport(mine, "2026-09-01", "September 2026"), last_month: missionReport([], "2026-08-01", "August 2026") })
    }
    const trustRoute = url.pathname.match(/^\/missions\/trust\/(\d+)$/)
    if (trustRoute && req.method === "PUT") {
      const b = JSON.parse((await readBody(req)).toString() || "{}")
      const t = { scope: `slow_day:${trustRoute[1]}`, streak: 0, auto: Boolean(b.auto), offered: true, business_id: Number(trustRoute[1]), business_name: "Chinar Café", trust_after: 3 }
      state.missionTrust[user.sub] = [t]
      return json(res, 200, t)
    }
    const r = url.pathname.match(/^\/missions\/(\d+)(?:\/(decide|undo))?$/)
    const m = r && mine.find((x) => x.id === Number(r[1]))
    if (!m) return json(res, 404, { detail: "No such mission." })
    if (!r[2]) return json(res, 200, { ...m, can_undo: Boolean(m.data.approved) && m.status === "active", trust: { scope: "slow_day:1", streak: 1, auto: false, offered: false }, trust_after: 3 })
    if (r[2] === "decide") {
      const b = JSON.parse((await readBody(req)).toString() || "{}")
      if (m.status !== "waiting") return json(res, 409, { detail: "That was already decided." }, { "X-Reason": "mission_decided" })
      if (b.decision === "approve" && !allowed) return json(res, 402, { detail: { detail: "Hangul handling your slow days is part of Plus.", code: "plan_required", plan_needed: "plus" } }, { "X-Reason": "plan_required" })
      const ok = b.decision === "approve"
      m.steps[2] = { ...m.steps[2], state: ok ? "done" : "skipped", note: ok ? "You said go ahead." : "You said not this time." }
      if (!ok) for (const s of m.steps) if (s.state === "todo") s.state = "skipped"
      m.status = ok ? "active" : "cancelled"
      m.done = m.steps.filter((s) => s.state === "done" || s.state === "skipped").length
      m.data.approved = ok
      return json(res, 200, { ...m, message: ok ? "Done. For Wednesday:\n1. Forward this to your regulars:\n\n" + m.data.share_text : "Okay, not this time." })
    }
    if (r[2] === "undo") {
      if (!m.data.approved || m.status !== "active") return json(res, 409, { detail: "It's too late to undo this one." })
      m.status = "cancelled"; m.data.undone = true
      for (const s of m.steps) if (s.state === "todo") s.state = "skipped"
      m.steps[2] = { ...m.steps[2], state: "skipped", note: "You undid this." }
      return json(res, 200, m)
    }
  }
  // ---- How's business (harness.sales): one business per user, built from business-fixture.json (the real overview)
  const bizPlan = () => state.businessPlan[user.sub] ?? "pro"
  const myBiz = () => state.business[user.sub]
  // the shop's customer list (db/customers.py): a light stand-in, no birthday parsing beyond "MM-DD"
  if (url.pathname === "/customers" && req.method === "GET") {
    const mine = state.customers[user.sub] ?? []
    const q = (url.searchParams.get("q") ?? "").toLowerCase()
    const rows = mine.filter((c) => !q || c.name.toLowerCase().includes(q) || c.phone.includes(q))
    return json(res, 200, { customers: rows, total: mine.length, today: "2026-10-10",
      birthdays: mine.filter((c) => c.birthday?.endsWith("10-12")).map((c) => ({ customer_id: c.id, name: c.name, date: "2026-10-12", in_days: 2, customer: true, phone: c.phone })),
      lapsed: mine.filter((c) => c.visits >= 3 && c.last_visit && c.last_visit < "2026-09-10").map((c) => ({ ...c, days_away: 40 })) })
  }
  if (url.pathname === "/customers" && req.method === "POST") {
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    if (!String(b.name ?? "").trim()) return json(res, 422, { detail: "Give the customer a name." })
    if (b.birthday && !/^(\d{1,2})[ /-]/.test(b.birthday) && !/[a-z]/i.test(b.birthday)) return json(res, 422, { detail: "That birthday isn't a real date (try 12/03 or 12 March)." })
    const mine = (state.customers[user.sub] ??= [])
    const c = { id: 800 + mine.length, name: b.name.trim(), phone: b.phone ? `+91${String(b.phone).replace(/\D/g, "").slice(-10)}` : "",
      birthday: b.birthday === "12 October" ? "10-12" : null, note: b.note ?? "", visits: 0, last_visit: null }
    mine.push(c)
    return json(res, 200, { ...c, created: true })
  }
  const custRoute = url.pathname.match(/^\/customers\/(\d+)(\/visit)?$/)
  if (custRoute) {
    const mine = state.customers[user.sub] ?? []
    const c = mine.find((x) => x.id === Number(custRoute[1]))
    if (!c) return json(res, 404, { detail: "No such customer." })
    if (custRoute[2] && req.method === "POST") {
      if (c.last_visit !== "2026-10-10") { c.visits += 1; c.last_visit = "2026-10-10" }
      return json(res, 200, c)
    }
    if (req.method === "DELETE") { state.customers[user.sub] = mine.filter((x) => x !== c); return json(res, 200, { removed: true }) }
  }
  if (url.pathname === "/business" && req.method === "GET") {
    const b = myBiz()
    return json(res, 200, { businesses: b ? [b.business] : [], slots: bizPlan() === "pro" ? 5 : 1, can_add: !b || bizPlan() === "pro",
      access: businessAccess(bizPlan()), kinds: [...LAUNCH_KINDS.map((k) => ({ key: k.key, label: k.label })), { key: "other", label: "Something else" }] })
  }
  if (url.pathname === "/business" && req.method === "POST") {
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    if (myBiz() && bizPlan() !== "pro") return json(res, 402, { detail: { detail: "Your plan includes 1 business. Pro tracks up to 5.", code: "business_limit", plan_needed: "pro" } }, { "X-Reason": "business_limit" })
    state.business[user.sub] = newBusiness(b, false)
    return json(res, 200, myBiz().business)
  }
  const bizRoute = url.pathname.match(/^\/business\/(\d+)(?:\/(overview|days|import|ideas\/([a-z0-9_]+)\/use|days\/(\d{4}-\d{2}-\d{2})))?$/)
  if (bizRoute) {
    const b = myBiz()
    if (!b || b.business.id !== Number(bizRoute[1])) return json(res, 404, { detail: "No such business." })
    const sub = bizRoute[2]
    if (sub === "overview" && req.method === "GET") return json(res, 200, businessOverview(b, bizPlan()))
    if (sub === "days" && req.method === "POST") {
      const d = JSON.parse((await readBody(req)).toString() || "{}")
      const day = d.day ?? BUSINESS_FIXTURE.overview.today
      b.days = b.days.filter((x) => x.day !== day).concat([{ day, sales: d.closed ? 0 : Number(d.sales ?? 0), bills: d.bills ?? null,
        closed: Boolean(d.closed), partial: false, promo: false, source: "page", note: "", rain_mm: null, tmax: null }]).sort((x, y) => x.day.localeCompare(y.day))
      return json(res, 200, b.days.find((x) => x.day === day))
    }
    if (sub?.startsWith("days/") && req.method === "DELETE") { b.days = b.days.filter((x) => x.day !== bizRoute[4]); return json(res, 200, { ok: true }) }
    if (sub === "import" && req.method === "POST") {
      const body = (await readBody(req)).toString()
      const preview = /name="preview"\r\n\r\ntrue/.test(body)
      const fx = BUSINESS_FIXTURE.overview.days
      const result = { days: fx.map((x) => ({ day: x.day, sales: x.sales, bills: x.bills })), date_col: "Date", amount_col: "Net Sales",
        rows_used: fx.length, rows_skipped: 0, columns: ["Date", "Orders", "Net Sales"], notes: [], from: fx[0].day, to: fx[fx.length - 1].day,
        total: fx.reduce((s2, x) => s2 + x.sales, 0), future_skipped: 0, saved: null }
      if (preview) return json(res, 200, result)
      const have = new Set(b.days.map((x) => x.day))
      const added = fx.filter((x) => !have.has(x.day))
      b.days = b.days.concat(added.map((x) => ({ ...x }))).sort((x, y) => x.day.localeCompare(y.day))
      return json(res, 200, { ...result, saved: { added: added.length, replaced: 0, kept: fx.length - added.length } })
    }
    if (sub?.startsWith("ideas/") && req.method === "POST") {
      const ov = businessOverview(b, bizPlan())
      const idea = ov.ideas.find((i) => i.key === bizRoute[3])
      if (!idea) return json(res, 402, { detail: { detail: "This idea isn't available on your plan this week.", code: "plan_required", plan_needed: "pro" } }, { "X-Reason": "plan_required" })
      b.ideasUsed = (b.ideasUsed ?? 0) + 1
      const q = new URLSearchParams(Object.entries({ tab: "create", layout: idea.layout, headline: idea.headline, subline: idea.subline,
        price: idea.price, cta: idea.cta, from: "business" }).filter(([, v]) => v))
      return json(res, 200, { idea, brand_id: b.business.brand_id, studio_url: b.business.brand_id ? `/brands/${b.business.brand_id}?${q}` : "/brands" })
    }
  }
  // ---- launch plans (harness.launch): a small café template; a sourced plan turns "ready" on its second read
  const launchAccess = () => state.launchAccess[user.sub] ?? { allowed: true, reason: null, detail: "", plan_needed: null, left: 3 }
  const myPlans = () => (state.launch[user.sub] ??= [])
  if (url.pathname === "/launch/kinds" && req.method === "GET") {
    return json(res, 200, { version: 1, renting: ["yes", "own", "no"], access: launchAccess(), kinds: LAUNCH_KINDS })
  }
  if (url.pathname === "/launch" && req.method === "GET") {
    return json(res, 200, myPlans().filter((p) => p.active).map((p) => {
      const v = launchView(p)
      return { id: v.id, title: v.title, kind: v.kind, city: v.city, area: v.area, status: v.status, sourced: v.sourced,
               created_at: v.created_at, updated_at: v.updated_at, startup_total: v.economics.startup_total,
               breakeven_per_day: v.economics.breakeven_per_day, profit: v.economics.profit, payback_months: v.economics.payback_months }
    }))
  }
  if (url.pathname === "/launch" && req.method === "POST") {
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    if (!LAUNCH_KINDS.some((k) => k.key === b.kind) || !String(b.city ?? "").trim()) return json(res, 422, { detail: "kind and city are required" })
    const acc = b.live === false ? { allowed: false, reason: "not_asked", detail: "", plan_needed: null, left: null } : launchAccess()
    const p = newLaunchPlan(900 + Object.values(state.launch).flat().length, b, acc.allowed)
    myPlans().push(p)
    return json(res, 200, { plan: launchView(p), access: acc })
  }
  const launchRoute = url.pathname.match(/^\/launch\/(\d+)(?:\/(source|export|items\/([a-z0-9_]+)\/refresh))?$/)
  if (launchRoute) {
    const p = myPlans().find((x) => x.id === Number(launchRoute[1]) && x.active)
    if (!p) return json(res, 404, { detail: "No such plan." })
    const sub = launchRoute[2]
    if (!sub && req.method === "GET") {
      if (p.status === "sourcing" && ++p.reads >= 2) launchSourced(p)
      return json(res, 200, launchView(p))
    }
    if (!sub && req.method === "PATCH") {
      const b = JSON.parse((await readBody(req)).toString() || "{}")
      for (const k of ["price", "units_per_day", "days_per_month", "working_capital_months"]) if (b[k] !== undefined) p.assumptions[k] = Number(b[k])
      for (const [k, e] of Object.entries(b.items ?? {})) {
        const it = p.items.find((x) => x.key === k)
        if (!it) return json(res, 422, { detail: `no such item: ${k}` })
        if (e.amount !== undefined) Object.assign(it, { amount: Number(e.amount), status: "user" })
        if (e.qty !== undefined) it.qty = Number(e.qty)
        if (e.include !== undefined) it.include = Boolean(e.include)
      }
      return json(res, 200, launchView(p))
    }
    if (!sub && req.method === "DELETE") { p.active = false; return json(res, 200, { ok: true }) }
    if (sub === "source" && req.method === "POST") {
      const acc = launchAccess()
      if (!acc.allowed) return json(res, 402, { detail: { detail: acc.detail, code: acc.reason, plan_needed: acc.plan_needed } }, { "X-Reason": acc.reason })
      Object.assign(p, { status: "sourcing", sourced: true, reads: 0 })
      return json(res, 200, launchView(p))
    }
    if (sub === "export" && req.method === "GET") {
      const fmt = url.searchParams.get("format") === "xlsx" ? "xlsx" : "pdf"
      res.writeHead(200, { "Content-Type": fmt === "pdf" ? "application/pdf" : "application/octet-stream",
                           "Content-Disposition": `attachment; filename="plan.${fmt}"` })
      return res.end(fmt === "pdf" ? "%PDF-1.4 fake" : "PK fake")
    }
    if (sub?.startsWith("items/") && req.method === "POST") return json(res, 200, launchView(p))
  }
  // ---- brands (harness.brands): slots default to Pro's 3; POST /__brands {user, slots?, brands?}
  const myBrands = () => (state.brands[user.sub] ??= [])
  const brandSlots = () => state.brandSlots[user.sub] ?? 3
  if (url.pathname === "/brands" && req.method === "GET") {
    const rows = myBrands().filter((b) => b.active !== false).map((b, i) => {
      const posts = (state.brandPosts[user.sub] ?? []).filter((p) => p.brand_id === b.id && p.active !== false)
      return { logo_dark: "", handle: "", website: "", cta: "", footer: "", hashtags: [], ...b, paused: i >= brandSlots(),
               posts: posts.length, cover: posts.at(-1)?.files[0]?.name ?? null }
    })
    return json(res, 200, { brands: rows, slots: brandSlots(), used: rows.length, can_add: rows.length < brandSlots(), templates_version: "1" })
  }
  if (url.pathname === "/brands/suggest" && req.method === "POST") {
    return json(res, 200, { kind: "cafe", label: "Café", name: "Chinar Café", looks: BRAND_LOOKS })
  }
  if (url.pathname === "/brands" && req.method === "POST") {
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    const rows = myBrands().filter((x) => x.active !== false)
    if (rows.length >= brandSlots()) {
      const free = brandSlots() === 0
      return json(res, 402, { detail: { detail: free ? "Brands are part of the Plus and Pro plans." : `You're using all ${brandSlots()} of your brand slots.`,
                                        code: "brand_limit", slots: brandSlots(), used: rows.length, plan_needed: free ? "plus" : null, buy: free ? null : "brand_slot" } },
                  { "X-Reason": "brand_limit" })
    }
    const look = BRAND_LOOKS.find((l) => l.id === b.look) ?? BRAND_LOOKS[0]
    const row = { id: 100 + rows.length + 1 + Object.values(state.brands).flat().length, name: String(b.name ?? "Brand"), kind: "cafe", look: look.id,
                  colors: b.colors ?? look.colors, style: look.style, voice: look.voice, font: b.font ?? look.font, logo: "", paused: false, active: true }
    myBrands().push(row)
    return json(res, 200, row)
  }
  const studioRoute = url.pathname.match(/^\/brands\/(\d+)\/(assets|preview|posts|logo)(?:\/(\d+))?$/)
  if (studioRoute) {
    const b = myBrands().find((x) => x.id === Number(studioRoute[1]) && x.active !== false)
    if (!b) return json(res, 404, { detail: "No such brand." })
    const assets = (state.brandAssets[b.id] ??= [])
    const what = studioRoute[2]
    if (what === "logo") {
      await readBody(req)
      b.logo = `brand-${b.id}-logo.png`; state.brandFiles.push(b.logo)
      return json(res, 200, { brand: b, suggested_colors: [{ role: "primary", hex: "#1F6F5C" }, { role: "secondary", hex: "#F4F1EA" },
                                                           { role: "accent", hex: "#E0A458" }, { role: "text", hex: "#1B2A24" }] })
    }
    if (what === "assets" && req.method === "GET") return json(res, 200, assets.filter((a) => a.active !== false))
    if (what === "assets" && req.method === "POST") {
      const buf = await readBody(req)
      const fname = (buf.toString("latin1").match(/filename="([^"]+)"/) ?? [])[1] ?? "photo.jpg"
      const a = { id: 500 + Object.values(state.brandAssets).flat().length, brand_id: b.id, name: `${b.id}-${fname.replace(/\.[^.]+$/, "")}.jpg`, width: 1200, height: 900, created_at: new Date().toISOString() }
      assets.unshift(a); state.brandFiles.push(a.name)
      return json(res, 200, a)
    }
    if (what === "assets" && req.method === "DELETE") {
      const a = assets.find((x) => x.id === Number(studioRoute[3]))
      if (!a) return json(res, 404, { detail: "No such photo." })
      a.active = false
      return json(res, 200, { ok: true })
    }
    if (what === "preview") {
      const d = JSON.parse((await readBody(req)).toString() || "{}")
      ;(state.previews ??= []).push(d)
      res.writeHead(200, { "Content-Type": "image/png" })
      return res.end(Buffer.from(PNG_1X1, "base64"))
    }
    if (what === "posts" && req.method === "GET") {
      return json(res, 200, (state.brandPosts[user.sub] ?? []).filter((p) => p.brand_id === b.id && p.active !== false).slice().reverse())
    }
    if (what === "posts" && req.method === "POST") {
      const d = JSON.parse((await readBody(req)).toString() || "{}")
      const slides = Array.isArray(d.slides) ? d.slides : []
      if (slides.length && (state.billing[user.sub]?.plan ?? "pro") !== "pro") {
        return json(res, 402, { detail: { detail: "Carousel posts is part of the Pro plan.", code: "plan_required", plan_needed: "pro" } }, { "X-Reason": "plan_required" })
      }
      const id = 900 + Object.values(state.brandPosts).flat().length
      const sizes = (d.sizes ?? ["post"]).filter((k) => !slides.length || ["post", "portrait"].includes(k))
      const n = slides.length ? slides.length + 1 : 1
      const files = sizes.flatMap((k) => Array.from({ length: n }, (_, i) => ({
        name: `post-${id}-${k}${slides.length ? `-${i + 1}` : ""}.jpg`, size: k, width: 1080, height: 1080, label: BRAND_SIZE_LABELS[k] ?? k,
        ...(slides.length ? { slide: i + 1 } : {}) })))
      state.brandFiles.push(...files.map((f) => f.name))
      const post = { id, brand_id: b.id, kind: slides.length ? "carousel" : "single", layout: d.layout ?? "band", words: d.words ?? {}, slides, sizes, files,
                     captions: {}, review_status: "none", review_comment: "", reviewed_at: null, created_at: new Date().toISOString() }
      ;(state.brandPosts[user.sub] ??= []).push(post)
      return json(res, 200, post)
    }
  }
  const postRoute = url.pathname.match(/^\/posts\/(\d+)(?:\/(zip|captions|review-link))?$/)
  if (postRoute) {
    const post = (state.brandPosts[user.sub] ?? []).find((x) => x.id === Number(postRoute[1]) && x.active !== false)
    if (!post) return json(res, 404, { detail: "No such post." })
    const what = postRoute[2]
    if (!what && req.method === "DELETE") { post.active = false; return json(res, 200, { ok: true }) }
    if (what === "zip") {
      res.writeHead(200, { "Content-Type": "application/zip", "Content-Disposition": `attachment; filename="post-${post.id}.zip"` })
      return res.end(Buffer.from("PK\x05\x06" + "\0".repeat(18), "latin1"))
    }
    if (what === "captions" && req.method === "POST") {
      const d = JSON.parse((await readBody(req)).toString() || "{}")
      for (const k of d.platforms ?? ["instagram"]) {
        post.captions[k] = { label: k[0].toUpperCase() + k.slice(1), text: `Fresh kahwa is back ☕ (${k})`, hashtags: k === "whatsapp" ? [] : ["#chinarcafe", "#kahwa"], first_comment: "" }
      }
      return json(res, 200, post)
    }
    if (what === "captions" && req.method === "PATCH") {
      const d = JSON.parse((await readBody(req)).toString() || "{}")
      post.captions[d.platform] = { ...(post.captions[d.platform] ?? { label: d.platform }), text: d.text, hashtags: d.hashtags ?? [], first_comment: d.first_comment ?? "" }
      return json(res, 200, post)
    }
    if (what === "review-link") {
      if ((state.billing[user.sub]?.plan ?? "pro") !== "pro") {
        return json(res, 402, { detail: { detail: "Client review links is part of the Pro plan.", code: "plan_required", plan_needed: "pro" } }, { "X-Reason": "plan_required" })
      }
      post.review_status = "waiting"; post.review_comment = ""
      const token = `review-${post.id}.${"x".repeat(43)}`
      return json(res, 200, { url: `http://localhost:3100/review/${token}`, token, expires_at: new Date(Date.now() + 14 * 864e5).toISOString() })
    }
  }
  const brandRoute = url.pathname.match(/^\/brands\/(\d+)$/)
  if (brandRoute) {
    const row = myBrands().find((b) => b.id === Number(brandRoute[1]) && b.active !== false)
    if (!row) return json(res, 404, { detail: "No such brand." })
    if (req.method === "DELETE") { row.active = false; return json(res, 200, { ok: true }) }
    if (req.method === "PATCH") { Object.assign(row, JSON.parse((await readBody(req)).toString() || "{}")); return json(res, 200, row) }
  }

  if (url.pathname === "/settings" && req.method === "GET") {
    // onboarded defaults to true so the walkthrough doesn't cover every other test; POST /__onboarding resets it
    return json(res, 200, { display_name: "", instructions: "", tone: "balanced", timezone: "UTC", language: "", city: "", onboarded: true,
                            ...(state.prefs[user.sub] ?? {}), tones: ["concise", "balanced", "detailed"] })
  }
  if (url.pathname === "/settings" && req.method === "PUT") {
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    if (!["concise", "balanced", "detailed"].includes(b.tone ?? "balanced")) return json(res, 422, { detail: "bad tone" })
    state.prefs[user.sub] = { ...(state.prefs[user.sub] ?? {}), display_name: b.display_name ?? "", instructions: b.instructions ?? "", tone: b.tone ?? "balanced", timezone: b.timezone ?? "UTC", language: b.language ?? "", city: b.city ?? "",
      // like the real backend: not sent = keep the stored one
      ...(b.persona !== undefined ? { persona: b.persona } : {}), ...(b.home_address !== undefined ? { home_address: b.home_address } : {}) }
    return json(res, 200, state.prefs[user.sub])
  }
  const userTasks = () => Object.values(state.tasks).filter((t) => t.user === user.sub)
  const pub = (t) => ({ ...Object.fromEntries(Object.entries(t).filter(([k]) => k !== "user")),
    asks_first: [...((t.connectors ?? []).includes("gmail") && /\b(send|reply|forward)\b/i.test(t.question ?? "") ? ["gmail"] : []),
                 ...(t.connectors ?? []).filter((a) => ["docs", "sheets"].includes(a))] })
  if (url.pathname === "/tasks" && req.method === "GET") return json(res, 200, userTasks().map(pub))
  // like POST /tasks/preview: apps the words switch on (a tiny keyword router), and the
  // actions a task may pre-approve, offered when Calendar / Gmail are "connected"
  if (url.pathname === "/tasks/preview" && req.method === "POST") {
    const q = String(JSON.parse((await readBody(req)).toString() || "{}").question ?? "")
    const apps = [...(/\b(event|slot|calendar|meeting)\b/i.test(q) ? ["calendar"] : []), ...(/\b(email|inbox|send|reply)\b/i.test(q) ? ["gmail"] : [])]
    if (/\b(sheet|spreadsheet)\b/i.test(q)) apps.push("sheets")
    return json(res, 200, { apps, connected: ["gmail", "calendar", "sheets"], title: q.split(/\s+/).slice(0, 7).join(" "),
      asks_first: [...(apps.includes("gmail") && /\b(send|reply|forward)\b/i.test(q) ? ["gmail"] : []),
                   ...apps.filter((a) => ["docs", "sheets"].includes(a))], lead_minutes: 5 })
  }
  if (url.pathname === "/tasks" && req.method === "POST") {
    const b = JSON.parse((await readBody(req)).toString() || "{}")
    if (!(b.every_minutes || b.daily_at)) return json(res, 422, { detail: "a schedule needs every_minutes or daily_at" })
    const id = Object.keys(state.tasks).length + 1
    state.tasks[id] = { id, user: user.sub, title: b.title || String(b.question ?? "").split(/\s+/).slice(0, 7).join(" "), question: b.question,
      days: b.days ?? null, run_on: b.run_on ?? null, every_minutes: b.every_minutes ?? null, daily_at: b.daily_at ?? null,
      connectors: b.connectors ?? [], mode: b.mode ?? "default", enabled: true, next_run_at: new Date(Date.now() + 3600e3).toISOString(),
      last_run_at: null, last_status: "never", last_run_id: null, last_answer: "", created_at: new Date().toISOString(),
      deliver_email: b.deliver_email === true }
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
    return json(res, 200, { google: state.google[user.sub] ?? { connected: false, products: [], scopes: [] },
                            apps: state.apps[user.sub] ?? {} })
  }
  const appRoute = url.pathname.match(/^\/integrations\/apps\/(github|notion|slack)$/)
  if (appRoute && req.method === "POST") {
    // like the real backend: no new work-app tokens (they're hidden); POST /__apps plants an old connection
    return json(res, 404, { detail: `${appRoute[1][0].toUpperCase() + appRoute[1].slice(1)} is no longer offered.` })
  }
  if (appRoute && req.method === "DELETE") { if (state.apps[user.sub]) delete state.apps[user.sub][appRoute[1]]; return json(res, 200, { disconnected: true }) }
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

function fakeMission(id) {
  const step = (key, label, s, note = "") => ({ key, label, state: s, note, at: null })
  return { id, kind: "slow_day", business_id: 1, target_day: "2026-09-16", status: "waiting", done: 2, total: 5,
    created_at: null, updated_at: null,
    steps: [step("spot", "Spotted Wednesday looks slow", "done", "About ₹9,000 expected; a usual Wednesday is ₹13,000."),
            step("prepare", "Make the offer post", "done", "A rainy-day offer: the post is ready in 2 sizes."),
            step("approve", "Your go-ahead", "waiting", "Waiting for your go-ahead."),
            step("check_in", "Ask how Wednesday went", "todo"), step("measure", "See if it worked", "todo")],
    data: { business_name: "Chinar Café", weekday: "Wednesday", brand_id: 200, post_id: 900, files: [],
      forecast: { value: 9000, low: 8000, high: 10000, typical: 13000 },
      idea: { key: "rain_offer", title: "A rainy-day offer", idea: "People stay in when it rains: push delivery with a small rainy-day offer.",
        margin_note: "After 10% off, each sale still leaves about ₹122.", track_note: "Tried once here: on average 14% above my forecast." },
      share_text: "*Rainy day? We deliver (10% OFF)*\nHot and fresh to your door" } }
}

function missionReport(ms, month, label) {
  const went = ms.filter((m) => m.data.approved && !m.data.undone)
  return { month, label, spotted: ms.length, went_ahead: went.length, on_their_own: 0, measured: 0, worked: 0, lift: 0, price: "Pro costs you ₹1,499", best: null }
}
