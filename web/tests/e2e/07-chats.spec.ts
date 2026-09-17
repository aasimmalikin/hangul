import { test, expect } from "@playwright/test"
import { freshUser, ask, backendState, expectReply, resetBackend, seedChat, signInAs } from "./helpers"

test.describe("chats rail", () => {
  // A fresh user per test: chat history is per user, and the BFF rate
  // limits are per user, so tests neither see each other's chats nor
  // share a bucket.
  let me = freshUser("chats")
  test.beforeEach(async ({ context, baseURL }) => {
    me = freshUser("chats")
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("starts empty, fills the whole left side, has its own scroll region, no 'Memory' wording", async ({ page }) => {
    await page.goto("/chat")
    const panel = page.getByTestId("chats-panel")
    await expect(panel).toContainText("Chats")
    await expect(panel).toContainText("No chats yet")
    await expect(panel).not.toContainText("Memory")
    await expect(panel.locator(".ti-brain")).toHaveCount(0)
    await expect(panel.locator(".h-sidebar-scroll")).toHaveCSS("overflow-y", "auto")
    const col = (await panel.boundingBox())!
    const sec = (await panel.getByTestId("chats-section").boundingBox())!
    expect(col.y + col.height).toBeCloseTo(page.viewportSize()!.height, 0)
    expect(sec.y).toBeCloseTo(col.y, 0)
    expect(sec.height).toBeCloseTo(col.height, 0)
    await expect(panel.getByText("Chats", { exact: true })).toHaveCSS("font-size", "12px")
  })

  test("every conversation is added to the rail and is there when the user is back on the landing page", async ({ page }) => {
    // first chat, from a landing-page prompt
    await page.goto("/")
    await expect(page.getByTestId("chats-panel")).toContainText("No chats yet")
    await page.getByRole("button", { name: "Draft a note" }).click()
    await expectReply(page, "Reply to: Draft a note")
    // …listed on /chat as soon as the run ends, titled by the first question
    const items = page.getByTestId("chats-item")
    await expect(items).toHaveCount(1)
    await expect(items.first()).toContainText("Draft a note")

    // a follow-up updates the same entry, it does not add a second one
    const savedAgain = page.waitForResponse((r) => r.url().endsWith("/api/chats") && r.request().method() === "POST")
    await ask(page, "and add a title")
    await expectReply(page, "Reply to: and add a title")
    expect((await savedAgain).status()).toBe(200)
    await expect(items).toHaveCount(1)
    const saved = (await backendState()).episodes[me.id]
    expect(saved).toHaveLength(1)
    expect(saved[0].summary).toContain("Q: Draft a note")
    expect(saved[0].summary).toContain("Q: and add a title")

    // back on the landing page: the chat is in the rail
    await page.goto("/")
    await expect(page.getByTestId("chats-item")).toHaveCount(1)
    await expect(page.getByTestId("chats-item").first()).toContainText("Draft a note")

    // second conversation → two entries, newest first
    await page.getByRole("button", { name: "Check the web" }).click()
    await expectReply(page, "Reply to: Check the web")
    await expect(page.getByTestId("chats-item")).toHaveCount(2)
    await expect(page.getByTestId("chats-item").first()).toContainText("Check the web")
    await expect(page.getByTestId("chats-item").last()).toContainText("Draft a note")
    await page.goto("/")
    await expect(page.getByTestId("chats-item")).toHaveCount(2)

    // reloading /chat and continuing does not create a duplicate entry
    await page.goto("/chat")
    await expect(page.locator(".h-prose")).toHaveCount(2)
    const savedMore = page.waitForResponse((r) => r.url().endsWith("/api/chats") && r.request().method() === "POST")
    await ask(page, "more")
    await expectReply(page, "Reply to: more")
    await savedMore
    await expect(page.getByTestId("chats-item")).toHaveCount(2)
    expect((await backendState()).episodes[me.id]).toHaveLength(2)
  })

  test("each row is the user's query only — cut with … when long, no model answer", async ({ page }) => {
    const long = "How do I rotate the API key for the billing service without any downtime for customers in the EU region?"
    await page.goto("/chat")
    await ask(page, long)
    await expectReply(page, `Reply to: ${long}`)
    const row = page.getByTestId("chats-item").first()
    const title = row.getByTestId("chats-title")
    await expect(title).toHaveText(long)                       // full text is there (and in the tooltip)…
    await expect(title).toHaveAttribute("title", long)
    await expect(title).toHaveCSS("text-overflow", "ellipsis") // …but drawn on one line, cut with …
    await expect(title).toHaveCSS("white-space", "nowrap")
    expect(await title.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true)
    // nothing from the model under it
    await expect(row).not.toContainText("Reply to")
    await expect(row.getByTestId("chats-preview")).toHaveCount(0)
  })

  test("hovering the header reveals 'View all'; it opens the full history with transcripts", async ({ page }) => {
    await seedChat(me, "Draft a note", { summary: "Q: Draft a note\nA: Here is a draft.\nQ: shorter\nA: Draft, shorter." })
    await seedChat(me, "Check the web")
    await page.goto("/")
    const panel = page.getByTestId("chats-panel")
    const viewAll = page.getByTestId("chats-view-all")
    const actions = panel.locator(".h-sidebar-actions")
    await expect(actions).toHaveCSS("opacity", "0")
    await panel.locator(".h-sidebar-head").hover()
    await expect(actions).toHaveCSS("opacity", "1")
    await expect(viewAll).toHaveAttribute("data-tip", "View all")
    await viewAll.hover()
    const tip = await viewAll.evaluate((el) => getComputedStyle(el, "::after").content)
    expect(tip).toBe('"View all"')

    await viewAll.click()
    const dialog = page.getByTestId("chats-history")
    await expect(dialog).toBeVisible()
    await expect(dialog).toContainText("All chats")
    const entries = dialog.getByTestId("chats-history-item")
    await expect(entries).toHaveCount(2)
    const draft = entries.filter({ hasText: "Draft a note" })
    await expect(draft).toContainText("Here is a draft.")
    await expect(draft).toContainText("shorter")
    await expect(draft).toContainText("Draft, shorter.")
    await page.keyboard.press("Escape")
    await expect(dialog).toHaveCount(0)
  })

  test("the settings button sorts by date: today, yesterday, custom", async ({ page }) => {
    const y = new Date(); y.setDate(y.getDate() - 1); y.setHours(10, 0, 0, 0)
    const old = new Date(2026, 0, 5, 9, 0, 0)
    await seedChat(me, "from today")
    await seedChat(me, "from yesterday", { updated_at: y.toISOString() })
    await seedChat(me, "from january", { updated_at: old.toISOString() })
    await page.goto("/")
    const items = page.getByTestId("chats-item")
    await expect(items).toHaveCount(3)

    const settings = page.getByTestId("chats-settings")
    await page.getByTestId("chats-panel").locator(".h-sidebar-head").hover()
    await expect(settings).toHaveAttribute("data-tip", "Sort by date")
    await settings.click()
    const menu = page.getByTestId("chats-sort-menu")
    await expect(menu).toContainText("Sort by date")
    await expect(menu.getByRole("menuitemradio")).toHaveText(["Today", "Yesterday", "Custom date"])

    await menu.getByRole("menuitemradio", { name: "Today" }).click()
    await expect(items).toHaveCount(1)
    await expect(items.first()).toContainText("from today")
    await expect(page.getByTestId("chats-filter-chip")).toContainText("Today")

    await settings.click()
    await page.getByTestId("chats-sort-menu").getByRole("menuitemradio", { name: "Yesterday" }).click()
    await expect(items).toHaveCount(1)
    await expect(items.first()).toContainText("from yesterday")

    await settings.click()
    await page.getByTestId("chats-sort-menu").getByRole("menuitemradio", { name: "Custom date" }).click()
    await page.getByTestId("chats-custom-date").fill("2026-01-05")
    await expect(items).toHaveCount(1)
    await expect(items.first()).toContainText("from january")
    await expect(page.getByTestId("chats-filter-chip")).toContainText("Jan 5, 2026")

    // a day with nothing says so; "view all" respects the filter too
    await page.getByTestId("chats-custom-date").fill("2026-01-06")
    await expect(page.getByTestId("chats-filter-empty")).toContainText("No chats on")
    await page.getByTestId("chats-view-all").click()
    await expect(page.getByTestId("chats-history")).toContainText("No chats on")
    await page.keyboard.press("Escape")

    // clear from the chip → everything again
    await page.getByTestId("chats-filter-chip").click()
    await expect(items).toHaveCount(3)
  })

  test("dots appear on hover, Delete turns red on hover, and deleting hides the chat without erasing it", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "remember this one")
    await expectReply(page, "Reply to: remember this one")
    const row = page.getByTestId("chats-item").filter({ hasText: "remember this one" })
    const dots = row.getByRole("button", { name: "Chat options" })

    await expect(dots).toHaveCSS("opacity", "0")
    await row.hover()
    await expect(dots).toHaveCSS("opacity", "1")

    await dots.click()
    const del = page.getByTestId("chats-delete")
    await expect(del).toBeVisible()
    const restColor = await del.evaluate((el) => getComputedStyle(el).color)
    const errColor = await del.evaluate(() => {
      const probe = document.createElement("span")
      probe.style.color = "var(--err)"
      document.body.appendChild(probe)
      const c = getComputedStyle(probe).color
      probe.remove()
      return c
    })
    expect(restColor).not.toBe(errColor)
    await del.hover()
    await expect(del).toHaveCSS("color", errColor)

    const deleted = page.waitForResponse((r) => r.url().includes("/api/chats/") && r.request().method() === "DELETE")
    await del.click()
    await expect(page.getByTestId("chats-item")).toHaveCount(0)
    expect((await deleted).status()).toBe(200)

    // deactivated, not deleted: still on the backend, flagged inactive
    const mine = (await backendState()).episodes[me.id]
    expect(mine).toHaveLength(1)
    expect(mine[0]).toMatchObject({ title: "remember this one", active: false })

    await page.goto("/")
    await expect(page.getByTestId("chats-panel")).toContainText("No chats yet")
  })

  test("a failed delete puts the chat back", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "keep me")
    await expectReply(page, "Reply to: keep me")
    await expect(page.getByTestId("chats-item")).toHaveCount(1)
    await page.route("**/api/chats/*", (r) => r.fulfill({ status: 502, contentType: "application/json", body: JSON.stringify({ detail: "The assistant is unreachable right now.", code: "upstream_unreachable" }) }))
    const row = page.getByTestId("chats-item").first()
    await row.hover()
    await row.getByRole("button", { name: "Chat options" }).click()
    await page.getByTestId("chats-delete").click()
    await expect(page.getByTestId("chats-item")).toHaveCount(1)
    await expect(page.getByTestId("chats-panel")).toContainText("unreachable")
  })

  test("the rail can be resized by dragging its edge; the width is remembered and clamps", async ({ page }) => {
    await page.goto("/chat")
    const panel = page.getByTestId("chats-panel")
    const grip = page.getByTestId("chats-resize")
    await expect(panel).toBeVisible()
    expect(Math.round((await panel.boundingBox())!.width)).toBe(264)

    const g = (await grip.boundingBox())!
    await page.mouse.move(g.x + g.width / 2, g.y + 200)
    await page.mouse.down()
    await page.mouse.move(g.x + g.width / 2 + 50, g.y + 200)
    await page.mouse.move(g.x + g.width / 2 + 100, g.y + 200)
    await page.mouse.up()
    expect(Math.round((await panel.boundingBox())!.width)).toBe(364)
    await expect(grip).toHaveAttribute("aria-valuenow", "364")

    await page.reload()
    await expect(page.getByTestId("chats-panel")).toBeVisible()
    expect(Math.round((await page.getByTestId("chats-panel").boundingBox())!.width)).toBe(364)

    const g2 = (await page.getByTestId("chats-resize").boundingBox())!
    await page.mouse.move(g2.x + g2.width / 2, g2.y + 200)
    await page.mouse.down()
    await page.mouse.move(g2.x + 600, g2.y + 200)
    await page.mouse.up()
    expect(Math.round((await page.getByTestId("chats-panel").boundingBox())!.width)).toBe(480)

    await page.getByTestId("chats-resize").dblclick()
    expect(Math.round((await page.getByTestId("chats-panel").boundingBox())!.width)).toBe(264)
  })

  test("the rail is on the landing page too, under the sigil + wordmark, right after sign-in", async ({ page }) => {
    await page.goto("/")
    const panel = page.getByTestId("chats-panel")
    await expect(panel).toBeVisible()
    await expect(panel).toContainText("Chats")
    await expect(page.getByPlaceholder("Ask anything…")).toBeVisible()
    const mark = page.locator("header").getByLabel("Hangul", { exact: true }).first()
    await expect(mark).toBeVisible()
    await expect(mark).toContainText("Hangul")
    await expect(mark.locator("svg")).toBeVisible()
    const m = (await mark.boundingBox())!
    const p = (await panel.boundingBox())!
    expect(m.y + m.height).toBeLessThanOrEqual(p.y + 1)
    expect(m.x).toBeLessThan(p.x + p.width)
  })

  test("signed-out visitors do not see the rail; it appears as soon as they sign in", async ({ page, context, baseURL }) => {
    await context.clearCookies()
    await page.goto("/chat")
    await expect(page.getByTestId("chats-panel")).toHaveCount(0)
    await signInAs(context, me, baseURL!)
    await page.reload()
    await expect(page.getByTestId("chats-panel")).toBeVisible()
  })
})
