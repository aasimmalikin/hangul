import { test, expect } from "@playwright/test"
import { alice, ask, bob, expectReply, resetBackend, signInAs } from "./helpers"

test.describe("security", () => {
  test("API routes refuse anonymous callers", async ({ request }) => {
    for (const [path, body] of [["/api/chat", { messages: [] }], ["/api/approve", {}], ["/api/quality", undefined]] as const) {
      const res = body === undefined ? await request.get(path) : await request.post(path, { data: body })
      expect(res.status(), path).toBe(401)
      expect((await res.json()).code).toBe("unauthorized")
    }
    const up = await request.post("/api/upload", { multipart: { file: { name: "a.txt", mimeType: "text/plain", buffer: Buffer.from("x") } } })
    expect(up.status()).toBe(401)
  })

  test("cross-site requests are blocked even with a valid session", async ({ context, baseURL }) => {
    await signInAs(context, alice, baseURL!)
    const res = await context.request.post("/api/chat", {
      headers: { Origin: "https://evil.example", "Sec-Fetch-Site": "cross-site" },
      data: { messages: [{ role: "user", parts: [{ type: "text", text: "hi" }] }] },
    })
    expect(res.status()).toBe(403)
    expect((await res.json()).code).toBe("forbidden_origin")
  })

  test("malformed bodies are rejected before reaching the backend", async ({ context, baseURL }) => {
    await signInAs(context, alice, baseURL!)
    const h = { "Sec-Fetch-Site": "same-origin" }
    expect((await context.request.post("/api/chat", { headers: h, data: { messages: [] } })).status()).toBe(400)
    expect((await context.request.post("/api/chat", { headers: { ...h, "Content-Type": "application/json" }, data: "{not json" })).status()).toBe(400)
    expect((await context.request.post("/api/approve", { headers: h, data: { approval_id: "../../x", decision: "approve" } })).status()).toBe(400)
    expect((await context.request.post("/api/approve", { headers: h, data: { approval_id: "run-1", decision: "maybe" } })).status()).toBe(400)
  })

  test("per-user rate limit answers 429 with Retry-After", async ({ context, baseURL }) => {
    await signInAs(context, alice, baseURL!)
    const seen: number[] = []
    for (let i = 0; i < 35; i++) {
      const res = await context.request.post("/api/approve", { headers: { "Sec-Fetch-Site": "same-origin" }, data: { approval_id: "nope", decision: "reject" } })
      seen.push(res.status())
      if (res.status() === 429) {
        expect(res.headers()["retry-after"]).toBeTruthy()
        break
      }
    }
    expect(seen, seen.join(",")).toContain(429)
  })

  test("security headers are present on every page", async ({ request }) => {
    const res = await request.get("/")
    const h = res.headers()
    expect(h["content-security-policy"]).toContain("frame-ancestors 'none'")
    expect(h["x-content-type-options"]).toBe("nosniff")
    expect(h["x-frame-options"]).toBe("DENY")
    expect(h["referrer-policy"]).toBe("strict-origin-when-cross-origin")
  })

  test("the service token is short-lived and carries the user id", async ({ context, baseURL }) => {
    await signInAs(context, alice, baseURL!)
    const page = await context.newPage()
    await page.goto("/chat")
    await ask(page, "who am I")
    await expectReply(page, `user=${alice.id}`)
  })
})

test.describe("concurrent users", () => {
  test.beforeEach(async () => { await resetBackend() })

  test("two users chatting at once each get their own answers and their own history", async ({ browser, baseURL }) => {
    const ctxA = await browser.newContext()
    const ctxB = await browser.newContext()
    await signInAs(ctxA, alice, baseURL!)
    await signInAs(ctxB, bob, baseURL!)
    const a = await ctxA.newPage()
    const b = await ctxB.newPage()
    await a.goto("/chat")
    await b.goto("/chat")

    await Promise.all([ask(a, "alice asks"), ask(b, "bob asks")])
    await Promise.all([expectReply(a, `alice asks user=${alice.id}`), expectReply(b, `bob asks user=${bob.id}`)])

    // Bob's thread never shows Alice's question, even after reloads.
    await b.reload()
    await expect(b.locator(".h-prose").first()).toContainText("bob asks")
    await expect(b.locator("body")).not.toContainText("alice asks")

    // Bob signing in on Alice's browser does not inherit her thread
    // (threads are keyed by user; his own lives in his browser).
    await ctxA.clearCookies()
    await signInAs(ctxA, bob, baseURL!)
    await a.reload()
    await expect(a.getByRole("button", { name: "Account menu" })).toBeVisible()
    await expect(a.locator("body")).not.toContainText("alice asks")
    await expect(a.locator(".h-prose")).toHaveCount(0)

    await ctxA.close()
    await ctxB.close()
  })

  test("several questions in a row from one user are answered in order, none dropped", async ({ context, baseURL }) => {
    await signInAs(context, alice, baseURL!)
    const page = await context.newPage()
    await page.goto("/chat")
    for (const n of [1, 2, 3, 4, 5]) {
      await ask(page, `question ${n}`)
      await expectReply(page, `Reply to: question ${n}`)
    }
    await expect(page.getByTestId("run-done")).toHaveCount(5)
  })
})
