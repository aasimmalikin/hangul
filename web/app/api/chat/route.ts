import { assertSameOrigin, jsonError, rateLimit, relayUpstreamError, requireUser, upstream, UpstreamError } from "@/lib/bff"

export const runtime = "nodejs"
export const maxDuration = 300

// Limits mirrored from the backend's AskRequest; enforced here too so a bad
// request is refused before a service token is minted or a slot is taken.
const MAX_QUESTION_CHARS = 8_000
const MAX_HISTORY_TURNS = 20
const MAX_HISTORY_CHARS = 4_000
/** Give up on a run if the backend goes silent this long (model hung, worker died). */
const STREAM_IDLE_MS = 120_000
/** Absolute cap on one run, matching `maxDuration`. */
const STREAM_TOTAL_MS = 290_000

type IncomingPart = { type: string; text?: string }
type IncomingMessage = { role: string; parts?: IncomingPart[]; content?: string }

const textOf = (m: IncomingMessage) =>
  (m.parts ?? []).filter((p) => p.type === "text" && p.text).map((p) => p.text).join("\n") || m.content || ""

/**
 * Translates the agent's SSE progress stream into an AI SDK UI message stream.
 *
 * The backend emits one event per thing the agent does — a turn's narration
 * tokens, each tool call, each tool result — and they are forwarded in order so
 * the user watches the run unfold instead of waiting on a final answer:
 *
 *   text_start/delta/end  ->  text parts (one block per agent turn)
 *   tool_call             ->  data-tool part, status "running"
 *   tool_result           ->  same data-tool part id, status "done" | "error"
 *   approval_required     ->  data-approval | data-choice part
 *   done                  ->  data-run part (steps, cost, tools) + finish
 *
 * The prior turns of the conversation go up as `history`, so follow-up
 * questions have context. The UI owns the transcript; the backend caps it.
 */
export async function POST(req: Request) {
  const blocked = assertSameOrigin(req)
  if (blocked) return blocked
  const who = await requireUser()
  if (who instanceof Response) return who
  const { userId } = who
  const limited = rateLimit(`chat:${userId}`, 60, 60_000)
  if (limited) return limited

  let body: { messages?: IncomingMessage[]; docsOnly?: unknown }
  try {
    body = await req.json()
  } catch {
    return jsonError(400, "bad_request", "Malformed request body.")
  }
  const messages = Array.isArray(body.messages) ? body.messages : []
  const last = messages[messages.length - 1]
  const question = last ? textOf(last).trim() : ""
  if (!question) return jsonError(400, "bad_request", "Ask a question first.")
  if (question.length > MAX_QUESTION_CHARS) {
    return jsonError(400, "bad_request", `Questions are limited to ${MAX_QUESTION_CHARS} characters.`)
  }

  const history = messages
    .slice(0, -1)
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m) => ({ role: m.role as "user" | "assistant", content: textOf(m).trim().slice(0, MAX_HISTORY_CHARS) }))
    .filter((m) => m.content)
    .slice(-MAX_HISTORY_TURNS)

  let res: Response
  try {
    res = await upstream("/ask/stream", userId, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ question, history, docs_only: body.docsOnly === true }),
    }, { timeoutMs: STREAM_TOTAL_MS, signal: req.signal })
  } catch (e) {
    if (e instanceof UpstreamError) return jsonError(e.status, e.code, e.message)
    throw e
  }
  if (!res.ok || !res.body) return relayUpstreamError(res)

  const encoder = new TextEncoder()
  const stream = new ReadableStream({
    async start(controller) {
      const reader = res.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ""

      // Arguments arrive on tool_call and are needed again on tool_result, so
      // the finished card can still say what was searched for.
      const callArgs = new Map<string, unknown>()
      const openBlocks = new Set<string>()
      const startedAt = Date.now()
      let finished = false

      const send = (obj: unknown) => controller.enqueue(encoder.encode(`data: ${JSON.stringify(obj)}\n\n`))
      const closeOpenBlocks = () => {
        for (const block of openBlocks) send({ type: "text-end", id: block })
        openBlocks.clear()
      }

      // Idle watchdog: if the backend stops talking (its own heartbeat pings
      // count as talking) the client gets a clear error instead of a spinner
      // that never ends.
      let idleTimer: ReturnType<typeof setTimeout> | undefined
      const armIdle = () => {
        clearTimeout(idleTimer)
        idleTimer = setTimeout(() => reader.cancel("idle").catch(() => {}), STREAM_IDLE_MS)
      }

      try {
        send({ type: "start" })
        armIdle()

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          armIdle()

          buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n")
          const events = buffer.split("\n\n")
          buffer = events.pop() ?? ""

          for (const evt of events) {
            let eventType = ""
            let dataStr = ""
            for (const line of evt.split("\n")) {
              if (line.startsWith("event:")) eventType = line.slice(6).trim()
              else if (line.startsWith("data:")) dataStr = line.slice(5).trim()
            }
            if (!dataStr) continue // heartbeat / comment line
            let data
            try { data = JSON.parse(dataStr) } catch { continue }

            switch (eventType) {
              case "text_start":
                openBlocks.add(data.block)
                send({ type: "text-start", id: data.block })
                break

              case "text_delta":
                send({ type: "text-delta", id: data.block, delta: data.text })
                break

              case "text_end":
                openBlocks.delete(data.block)
                send({ type: "text-end", id: data.block })
                break

              case "tool_call":
                callArgs.set(data.id, data.arguments)
                send({
                  type: "data-tool",
                  id: data.id,
                  data: { tool: data.name, arguments: data.arguments, status: "running", step: data.step },
                })
                break

              case "tool_result":
                // Same id as the tool_call above, so this replaces that part
                // rather than appending a second one.
                send({
                  type: "data-tool",
                  id: data.id,
                  data: {
                    tool: data.name,
                    arguments: callArgs.get(data.id) ?? {},
                    status: data.ok ? "done" : "error",
                    preview: data.preview,
                    ms: data.ms,
                    cached: data.cached,
                  },
                })
                break

              case "approval_required":
                if (data.name === "ask_user") {
                  send({
                    type: "data-choice",
                    data: { runId: data.run_id, question: data.arguments.question, options: data.arguments.options ?? [] },
                  })
                } else {
                  send({
                    type: "data-approval",
                    data: { runId: data.run_id, tool: data.name, arguments: data.arguments },
                  })
                }
                break

              case "done":
                closeOpenBlocks()
                send({
                  type: "data-run",
                  data: {
                    runId: data.run_id,
                    steps: data.steps,
                    costUsd: data.cost_usd,
                    toolsUsed: data.tools_used ?? [],
                    ms: Date.now() - startedAt,
                  },
                })
                send({ type: "finish" })
                finished = true
                break

              case "error":
                closeOpenBlocks()
                send({ type: "error", errorText: data.message })
                finished = true
                break
            }
          }
        }
        if (!finished) {
          // Backend closed the stream without done/error: worker restarted,
          // proxy cut the connection, or the idle watchdog fired.
          closeOpenBlocks()
          send({ type: "error", errorText: "The connection to the assistant was interrupted." })
        }
      } catch (e) {
        closeOpenBlocks()
        if (!finished) {
          const msg = (e as Error)?.message === "idle"
            ? "The assistant stopped responding."
            : "The connection to the assistant was interrupted."
          send({ type: "error", errorText: msg })
        }
      } finally {
        clearTimeout(idleTimer)
        try { controller.close() } catch { /* already closed */ }
      }
    },
    cancel() {
      // Client went away (tab closed, navigation): drop our side so the
      // backend sees the disconnect and cancels the run.
      res.body?.cancel().catch(() => {})
    },
  })

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
      "x-vercel-ai-ui-message-stream": "v1",
    },
  })
}
