import { test, expect } from "@playwright/test"
import { ask, backendState, expectReply, freshUser, resetBackend, seedChat, signInAs } from "./helpers"

/**
 * Conversations are server-owned: many at once, each with its own context,
 * reopenable from the rail in a tab that has never shown them.
 *
 * Before this, a conversation lived only in a tab's sessionStorage, so a second
 * chat needed a second tab and nothing could be reopened at all. These tests
 * pin the behaviour that replaced it.
 */
test.describe("conversations", () => {
  let me = freshUser("convs")
  test.beforeEach(async ({ context, baseURL }) => {
    me = freshUser("convs")
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("the first message creates a conversation and the follow-up continues it", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "first question")
    await expectReply(page, "Reply to: first question")

    const first = await backendState()
    const convs = first.conversations[me.id]
    expect(convs).toHaveLength(1)
    expect(convs[0].title).toBe("first question")   // named from the first question

    await ask(page, "second question")
    await expectReply(page, "Reply to: second question")

    const after = await backendState()
    // still ONE conversation, and the second ask named it
    expect(after.conversations[me.id]).toHaveLength(1)
    const asks = after.asks.filter((a) => a.user === me.id)
    expect(asks[0].conversation_id).toBeNull()
    expect(asks[1].conversation_id).toBe(convs[0].id)
    // the client stopped uploading history: the server has the transcript
    expect(asks[1].history).toBe(0)
  })

  test("a past conversation reopens from the rail, in a tab that never showed it", async ({ page }) => {
    const { id } = await seedChat(me, "the billing key rotation", {
      messages: [
        { role: "user", content: "the billing key rotation" },
        { role: "assistant", content: "Rotate the secondary key first." },
        { role: "user", content: "and the EU region?" },
        { role: "assistant", content: "EU has its own keyring." },
      ],
    })

    // A fresh page: nothing in this tab's sessionStorage for that chat.
    await page.goto("/chat")
    await expect(page.locator(".h-prose")).toHaveCount(0)

    const row = page.getByTestId("chats-item").filter({ hasText: "the billing key rotation" })
    await row.getByTestId("chats-open").click()

    // The whole stored transcript comes back from the server.
    await expect(page).toHaveURL(new RegExp(`/chat\\?c=${id}`))
    const thread = page.getByTestId("thread")
    await expect(thread).toContainText("Rotate the secondary key first.")
    await expect(thread).toContainText("and the EU region?")
    await expect(thread).toContainText("EU has its own keyring.")
    await expect(page.locator(".h-prose")).toHaveCount(4)   // 2 questions + 2 answers

    // …and continuing it goes to that same conversation, not a new one.
    await ask(page, "what about staging?")
    await expectReply(page, "Reply to: what about staging?")
    const state = await backendState()
    expect(state.conversations[me.id]).toHaveLength(1)
    expect(state.asks.filter((a) => a.user === me.id).at(-1)!.conversation_id).toBe(id)
  })

  test("a reopened conversation survives a reload with cleared session storage", async ({ page }) => {
    const { id } = await seedChat(me, "quarterly numbers", {
      messages: [{ role: "user", content: "quarterly numbers" },
                 { role: "assistant", content: "Revenue was 4.2M." }],
    })
    await page.goto(`/chat?c=${id}`)
    await expect(page.getByTestId("thread")).toContainText("Revenue was 4.2M.")

    // Wipe the optimistic cache: the server is the record, so it still loads.
    await page.evaluate(() => sessionStorage.clear())
    await page.reload()
    await expect(page.getByTestId("thread")).toContainText("Revenue was 4.2M.")
  })

  test("two conversations in one tab never mix their context", async ({ page }) => {
    const a = await seedChat(me, "chat about cats", {
      messages: [{ role: "user", content: "chat about cats" }, { role: "assistant", content: "Cats purr." }] })
    const b = await seedChat(me, "chat about dogs", {
      messages: [{ role: "user", content: "chat about dogs" }, { role: "assistant", content: "Dogs bark." }] })

    await page.goto(`/chat?c=${a.id}`)
    await expect(page.getByTestId("thread")).toContainText("Cats purr.")
    await expect(page.getByTestId("thread")).not.toContainText("Dogs bark.")

    // switch via the rail
    await page.getByTestId("chats-item").filter({ hasText: "chat about dogs" }).getByTestId("chats-open").click()
    await expect(page.getByTestId("thread")).toContainText("Dogs bark.")
    await expect(page.getByTestId("thread")).not.toContainText("Cats purr.")

    // and back again — the first one is intact
    await page.getByTestId("chats-item").filter({ hasText: "chat about cats" }).getByTestId("chats-open").click()
    await expect(page.getByTestId("thread")).toContainText("Cats purr.")
  })

  test("'New chat' starts a fresh conversation rather than continuing the open one", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "the old chat")
    await expectReply(page, "Reply to: the old chat")
    const firstId = (await backendState()).conversations[me.id][0].id

    await page.getByRole("button", { name: /New chat/i }).click()
    await expect(page.locator(".h-prose")).toHaveCount(0)

    await ask(page, "the new chat")
    await expectReply(page, "Reply to: the new chat")
    const state = await backendState()
    expect(state.conversations[me.id]).toHaveLength(2)
    // the new run did NOT carry the old conversation's id
    expect(state.asks.filter((a) => a.user === me.id).at(-1)!.conversation_id).not.toBe(firstId)
  })

  test("the rail marks which conversation is on screen", async ({ page }) => {
    const a = await seedChat(me, "alpha chat")
    await seedChat(me, "beta chat")
    await page.goto(`/chat?c=${a.id}`)
    const alpha = page.getByTestId("chats-item").filter({ hasText: "alpha chat" }).getByTestId("chats-open")
    const beta = page.getByTestId("chats-item").filter({ hasText: "beta chat" }).getByTestId("chats-open")
    await expect(alpha).toHaveAttribute("aria-current", "true")
    await expect(beta).not.toHaveAttribute("aria-current", "true")
  })

  test("a conversation that already has a run in flight answers 409", async ({ page }) => {
    // Drive the API directly: the composer is disabled mid-stream, so the 409
    // is a backstop for a second device or a retried request, not something
    // the UI can produce on its own.
    const { id } = await seedChat(me, "busy chat")
    const body = { messages: [{ role: "user", parts: [{ type: "text", text: "SLOW one" }] }], conversationId: id }

    await page.goto("/chat")
    const both = await page.evaluate(async (payload) => {
      const post = () => fetch("/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      }).then((r) => r.status)
      // second request starts while the first is still streaming
      const first = post()
      await new Promise((r) => setTimeout(r, 400))
      const second = await post()
      return { second, first: await first }
    }, body)

    expect(both.first).toBe(200)
    expect(both.second).toBe(409)
  })

  test("deleting the open conversation clears it from the rail", async ({ page }) => {
    const { id } = await seedChat(me, "to be deleted", {
      messages: [{ role: "user", content: "to be deleted" }, { role: "assistant", content: "Here you go." }] })
    await page.goto(`/chat?c=${id}`)
    await expect(page.getByTestId("thread")).toContainText("Here you go.")

    const row = page.getByTestId("chats-item").first()
    await row.hover()
    await row.getByRole("button", { name: "Chat options" }).click()
    await page.getByTestId("chats-delete").click()
    await expect(page.getByTestId("chats-item")).toHaveCount(0)

    // hidden, not erased
    const mine = (await backendState()).conversations[me.id]
    expect(mine[0]).toMatchObject({ title: "to be deleted", active: false })
  })
})
