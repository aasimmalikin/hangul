import { test, expect } from "@playwright/test"
import { ask, backend, freshUser, resetBackend, signInAs } from "./helpers"

/**
 * Kept: everything the user asked Hangul to do, in their words, on one line
 * through time -- done before the now line, waiting after it -- with search,
 * row actions and a badge for what needs them.
 */
test.describe("Kept", () => {
  const me = freshUser("kept")
  const inHours = (h: number) => new Date(Date.now() + h * 3_600_000).toISOString()

  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("an empty Kept says how things get here", async ({ page }) => {
    await page.goto("/kept")
    await expect(page.getByTestId("kept-empty")).toContainText("remind me to call mum at 6")
    await expect(page.getByTestId("kept-badge")).toHaveCount(0)
  })

  test("the Day line puts what's done before now and what's coming after, in the user's words", async ({ page }) => {
    await backend("/__reminder", { user: me.id, text: "Call mum", status: "pending", due_at: inHours(30),
                                   said: "Remind me to call mum tomorrow evening", conversation_id: "c-mum" })
    await backend("/__kept", { user: me.id, items: [
      { id: "action:1", kind: "action", state: "done", did: "Made “Expenses” (PDF)", said: "September expenses as a PDF",
        when: new Date(Date.now() - 60_000).toISOString(), app: "File", conversation_id: "c-pdf", ref: { id: 1 } },
      { id: "task:1", kind: "task", state: "coming", did: "Morning brief · Every day at 08:00", said: "Brief me every morning",
        when: inHours(50), app: "Scheduled", conversation_id: null, ref: { id: 1, repeats: true } },
    ] })
    await page.goto("/kept")
    await expect(page.getByTestId("kept-now")).toBeVisible()
    await expect(page.getByTestId("lane-today")).toContainText("September expenses as a PDF")
    await expect(page.getByTestId("lane-today")).toContainText("Made “Expenses” (PDF)")
    const ahead = page.getByTestId("lane-ahead")
    await expect(ahead.getByTestId("kept-reminder:1")).toContainText("Remind me to call mum tomorrow evening")
    await expect(ahead.getByTestId("kept-task:1")).toContainText("repeats")
    // a row opens the chat it came from
    await expect(page.getByTestId("kept-action:1").getByRole("link", { name: "Open the chat" })).toHaveAttribute("href", "/chat?c=c-pdf")
    // and can be undone from the row
    await ahead.getByTestId("kept-reminder:1").getByRole("button", { name: "Cancel" }).click()
    await expect(page.locator(".h-kept-toast")).toContainText("Reminder cancelled")
    await expect(page.getByTestId("kept-reminder:1")).toHaveCount(0)
    await expect.poll(async () => (await backend("/__state")).reminders[me.id][0].status).toBe("cancelled")
  })

  test("an action waiting for approval is badged, reviewable and can be rejected from Kept", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "APPROVAL write the notes")
    await expect(page.getByRole("button", { name: /approve/i }).first()).toBeVisible()
    await expect(page.getByTestId("kept-badge").first()).toHaveText("1")
    await page.getByTestId("nav-Kept").click()
    const row = page.locator("[data-testid^='kept-approval:']")
    await expect(row).toHaveAttribute("data-state", "needs_you")
    await expect(row).toContainText("Save my notes to a file")
    await expect(page.getByText("1 thing needs you")).toBeVisible()
    await expect(row.getByRole("link", { name: "Review" })).toHaveAttribute("href", /\/chat\?c=/)
    await row.getByRole("button", { name: "Reject" }).click()
    await expect(page.locator(".h-kept-toast")).toContainText("Rejected")
    await expect(row).toHaveCount(0)
    await expect(page.getByTestId("kept-badge")).toHaveCount(0)
  })

  test("search reaches undated things and says what it found", async ({ page }) => {
    await backend("/__reminder", { user: me.id, text: "Call mum", status: "pending", due_at: inHours(3), said: "Remind me to call mum at 6" })
    await page.goto("/kept#holding")
    await page.getByLabel("New item").fill("Saffron for mum")
    await page.getByRole("button", { name: "Add" }).click()
    await expect(page.getByTestId("list-To-do")).toContainText("Saffron for mum")
    await page.keyboard.press("Escape")
    await page.locator("body").click()
    await page.keyboard.press("/")                                   // "/" jumps to the search box
    await expect(page.getByTestId("kept-search")).toBeFocused()
    await page.keyboard.type("what did I ask about mum")
    await expect(page.getByTestId("kept-summary")).toContainText("2 things for “what did I ask about mum”: 1 coming up, 1 kept.")
    await expect(page.getByTestId("kept-results").locator("mark").first()).toHaveText(/mum/i)
    await page.getByRole("button", { name: /^Kept · 1$/ }).click()  // filter to undated things
    await expect(page.getByTestId("kept-results").locator("article")).toHaveCount(1)
    await page.getByTestId("kept-results").getByRole("button", { name: "Tick off" }).click()
    await expect.poll(async () => (await backend("/__state")).todos[me.id][0].done).toBe(true)
    await page.getByRole("button", { name: "Clear search" }).click()
    await expect(page.getByTestId("kept-line")).toBeVisible()
  })

  test.describe("on a phone", () => {
    test.use({ viewport: { width: 390, height: 844 } })

    test("Kept is under You on a phone, the lanes stack and the search sits by the thumb", async ({ page }) => {
      await backend("/__reminder", { user: me.id, text: "Call mum", status: "pending", due_at: inHours(3), said: "Remind me to call mum at 6" })
      await page.goto("/")
      await page.locator(".h-bottom-nav").getByRole("link", { name: "You" }).click()
      await page.getByTestId("you-kept").click()
      await expect(page).toHaveURL(/\/kept$/)
      await expect(page.getByTestId("kept-reminder:1")).toBeVisible()
      const search = await page.getByTestId("kept-search").boundingBox()
      expect(search!.y).toBeGreaterThan(600)                           // near the bottom of an 844px screen
      const width = await page.evaluate(() => document.documentElement.scrollWidth)
      expect(width).toBeLessThanOrEqual(390)                           // no sideways scroll
    })
  })
})
