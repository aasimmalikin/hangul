import { test, expect } from "@playwright/test"
import { freshUser, ask, backendState, expectReply, resetBackend, signInAs } from "./helpers"

test.describe("conversation", () => {
  const me = freshUser("conversation")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("streams the answer and shows the tool row, with no cost/steps chatter", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "What is the policy?")
    await expectReply(page, "Reply to: What is the policy?")
    await expect(page.getByText("Searched your documents")).toBeVisible()
    await expect(page.locator("body")).not.toContainText(/\$0\.00|steps/)
  })

  test("follow-ups continue the same conversation instead of re-uploading history", async ({ page }) => {
    // The server owns the transcript now, so a follow-up names the conversation
    // rather than shipping the earlier turns back up (which only ever carried
    // user/assistant text, never the tool results).
    await page.goto("/chat")
    await ask(page, "first")
    await expectReply(page, "Reply to: first")
    await ask(page, "HISTORY how many?")
    await expectReply(page, "history=0")
    const s = await backendState()
    const convs = s.conversations[me.id]
    expect(convs).toHaveLength(1)                         // one conversation, two turns
    expect(s.asks[0].conversation_id).toBeNull()          // first turn creates it
    expect(s.asks[1].conversation_id).toBe(convs[0].id)   // the follow-up continues it
    expect(s.asks[1].history).toBe(0)
  })

  test("documents-only toggle is sent with the question", async ({ page }) => {
    await page.goto("/chat")
    await page.getByTestId("docs-only").click()
    await expect(page.getByTestId("docs-only")).toHaveAttribute("aria-pressed", "true")
    await ask(page, "only from docs")
    await expectReply(page, "docs_only=true")
    const s = await backendState()
    expect(s.asks[0].docs_only).toBe(true)
  })

  test("model and effort picked in the composer are sent, and survive a refresh", async ({ page }) => {
    await page.goto("/chat")
    // Nothing chosen: the chips show the server default and nothing is sent.
    await expect(page.getByTestId("model-picker")).toContainText("Fake Reasoner")
    await expect(page.getByTestId("effort-picker")).toContainText("medium")

    await page.getByTestId("effort-picker").click()
    await page.getByTestId("effort-option-high").click()
    await ask(page, "think hard")
    await expectReply(page, "model=fake-reasoner effort=high")
    let s = await backendState()
    expect(s.asks[0]).toMatchObject({ model: "fake-reasoner", effort: "high" })

    await page.reload()
    await expect(page.getByTestId("effort-picker")).toContainText("high")

    // A model without reasoning drops the effort chip and sends no effort.
    await page.getByTestId("model-picker").click()
    await page.getByTestId("model-option-fake-plain").click()
    await expect(page.getByTestId("model-picker")).toContainText("Fake Plain")
    await expect(page.getByTestId("effort-picker")).toHaveCount(0)
    await ask(page, "plain please")
    await expectReply(page, "model=fake-plain")
    s = await backendState()
    expect(s.asks[1]).toMatchObject({ model: "fake-plain", effort: null })
  })

  test("refresh keeps the thread and does not re-send; ?q= is consumed once", async ({ page }) => {
    await page.goto("/chat?q=From+the+landing+page")
    await expectReply(page, "Reply to: From the landing page")
    await expect(page).toHaveURL(/\/chat$/)
    await ask(page, "second")
    await expectReply(page, "Reply to: second")

    await page.reload()
    await expect(page.locator(".h-prose")).toHaveCount(4)
    await expect(page.getByTestId("run-done")).toHaveCount(2)
    await page.waitForTimeout(500)
    expect((await backendState()).asks).toHaveLength(2)
  })

  test("each landing-page prompt starts a fresh conversation, never continuing the last one", async ({ page }) => {
    // Draft a note → chat
    await page.goto("/")
    await page.getByRole("button", { name: "Draft a note" }).click()
    await expect(page).toHaveURL(/\/chat/)
    await expectReply(page, "Reply to: Draft a note")
    await ask(page, "and add a title")
    await expectReply(page, "Reply to: and add a title")
    await expect(page.locator(".h-prose")).toHaveCount(4)

    // back to the landing page, pick another prompt → only the new exchange is shown
    await page.goto("/")
    await page.getByRole("button", { name: "Check the web" }).click()
    await expectReply(page, "Reply to: Check the web")
    await expect(page.locator(".h-prose")).toHaveCount(2)
    // Scoped to the thread: the Chats rail lists "Draft a note" as past history,
    // which is correct — what must not happen is it being in THIS conversation.
    await expect(page.getByTestId("thread")).not.toContainText("Draft a note")
    // and the backend got it with no history from the earlier thread
    const asks = (await backendState()).asks
    expect(asks.at(-1)).toMatchObject({ question: "Check the web", history: 0 })

    // third prompt, same rule
    await page.goto("/")
    await page.getByRole("button", { name: "Search my documents" }).click()
    await expectReply(page, "Reply to: Search my documents")
    await expect(page.locator(".h-prose")).toHaveCount(2)
    await expect(page.getByTestId("thread")).not.toContainText("Check the web")

    // a plain refresh (no ?q=) still restores the current thread
    await page.reload()
    await expect(page.locator(".h-prose")).toHaveCount(2)
    await expect(page.locator("body")).toContainText("Search my documents")
  })

  test("back then forward restores the thread", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "before navigating")
    await expectReply(page, "before navigating")
    await page.goto("/")
    await page.goBack()
    await expect(page.locator(".h-prose").first()).toContainText("before navigating")
    await page.goForward()
    await page.goBack()
    await expect(page.locator(".h-prose").first()).toContainText("before navigating")
    expect((await backendState()).asks).toHaveLength(1)
  })

  test("New chat clears the thread and storage", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "to be cleared")
    await expectReply(page, "to be cleared")
    await page.getByRole("button", { name: "New chat" }).click()
    await expect(page.locator(".h-prose")).toHaveCount(0)
    await page.reload()
    await expect(page.locator(".h-prose")).toHaveCount(0)
  })

  test("a second tab is its own conversation; neither tab sees the other's messages", async ({ page, context }) => {
    await page.goto("/chat")
    await ask(page, "from tab one")
    await expectReply(page, "from tab one")
    const tab2 = await context.newPage()
    await tab2.goto("/chat")
    await expect(tab2.locator(".h-prose")).toHaveCount(0)
    await ask(tab2, "from tab two")
    await expectReply(tab2, "from tab two")
    // (the Chats rail lists both conversations in both tabs — that is per
    // user, not per tab; the *thread* is what must stay separate)
    await expect(tab2.getByTestId("thread")).not.toContainText("from tab one")
    await expect(page.getByTestId("thread")).not.toContainText("from tab two")
    await expect(page.locator(".h-prose")).toHaveCount(2)
    // each tab keeps its own thread across a refresh
    await tab2.reload()
    await expect(tab2.locator(".h-prose").first()).toContainText("from tab two")
    await page.reload()
    await expect(page.locator(".h-prose").first()).toContainText("from tab one")
  })

  test("Stop ends a slow answer and leaves a retry", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "SLOW take your time")
    await expect(page.getByTestId("thinking")).toBeVisible()
    await page.getByRole("button", { name: "Stop" }).click()
    await expect(page.getByRole("button", { name: "Send" })).toBeVisible()
    await expect(page.getByTestId("notice-card")).toBeVisible()
    await expect(page.getByTestId("retry")).toBeEnabled()
  })

  test("over-long question is refused before sending", async ({ page }) => {
    await page.goto("/chat")
    const ta = page.getByPlaceholder(/Ask/)
    await ta.fill("x".repeat(8_000))
    await expect(ta).toHaveValue("x".repeat(8_000)) // maxLength clamps at the limit
    await page.keyboard.press("Enter")
    await expectReply(page, "Reply to: xxx")
  })
})
