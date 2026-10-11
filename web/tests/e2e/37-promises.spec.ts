import { test, expect } from "@playwright/test"
import { backend, backendState, freshUser, resetBackend, signInAs } from "./helpers"

/**
 * Kept your word: promises the user owes and is owed on Today, "was anything
 * promised?" after a meeting, the prep line under Next up, chasing (Plus) and
 * Kept's row actions, and the email switch in Settings.
 */
test.describe("Kept your word", () => {
  const me = freshUser("word")
  const meeting = { id: "ev1", summary: "Q3 review", people: [{ name: "Priya Sharma", email: "priya@acme.in" }] }

  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("Today lists what you owe and what's owed to you, late ones first", async ({ page }) => {
    await backend("/__promises", { user: me.id, promises: [
      { direction: "mine", what: "Send the deck", who: "Priya", due_on: "2026-10-03" },
      { direction: "theirs", what: "Share the plan", who: "Sam", due_on: "2026-10-09" },
      { direction: "theirs", what: "Send the quote", who: "Rahul", due_on: "2026-09-30" },
    ] })
    await page.goto("/")
    const card = page.getByTestId("today-promises")
    await expect(card.getByTestId("promises-mine")).toContainText("Send the deck")
    await expect(card.getByTestId("promises-mine")).toContainText("for Priya")
    const theirs = card.getByTestId("promises-theirs")
    await expect(theirs).toContainText("Owed to you · 2")
    await expect(theirs.locator(".h-word-row").first()).toContainText("Send the quote")
    // only the late one can be chased; Kept takes a row away at once
    await expect(theirs.getByRole("button", { name: "Chase" })).toHaveCount(1)
    await card.getByRole("button", { name: "Kept: Send the deck" }).click()
    await expect(card.getByTestId("promises-mine")).toHaveCount(0)
    await expect.poll(async () => (await backendState() as unknown as { promises: Record<string, Array<{ what: string; status: string }>> })
      .promises[me.id].find((p) => p.what === "Send the deck")?.status).toBe("done")
  })

  test("Chase drafts a follow-up in chat", async ({ page }) => {
    await backend("/__promises", { user: me.id, promises: [{ direction: "theirs", what: "Send the quote", who: "Rahul", due_on: "2026-09-30" }] })
    await page.goto("/")
    await page.getByTestId("today-promises").getByRole("button", { name: "Chase" }).click()
    await expect(page).toHaveURL(/\/chat/)
    await expect(page.getByText(/follow-up email to Rahul/).first()).toBeVisible()
  })

  test("after a meeting: say what was promised, and it's kept", async ({ page }) => {
    await backend("/__promises", { user: me.id, asking: [meeting] })
    await page.goto("/")
    const ask = page.getByTestId("promise-ask")
    await expect(ask).toContainText("How did Q3 review with Priya Sharma go?")
    await page.getByTestId("promise-ask-input").fill("I'll send the deck Friday and Priya will share the numbers")
    await page.getByTestId("promise-ask-save").click()
    await expect(page.getByTestId("promise-note")).toContainText("Kept 2 promises from “Q3 review”")
    await expect(page.getByTestId("promise-ask")).toHaveCount(0)
    await expect(page.getByTestId("promises-mine")).toContainText("Send the deck Friday")
    await expect(page.getByTestId("promises-theirs")).toContainText("Share the numbers")
  })

  test("nothing promised: the question goes away", async ({ page }) => {
    await backend("/__promises", { user: me.id, asking: [meeting] })
    await page.goto("/")
    await page.getByTestId("promise-ask-nothing").click()
    await expect(page.getByTestId("promise-ask")).toHaveCount(0)
    await expect.poll(async () => (await backendState() as unknown as { promiseAsking: Record<string, unknown[]> }).promiseAsking[me.id]).toEqual([])
  })

  test("on Free, the after-meeting answer and chasing offer Plus", async ({ page }) => {
    await backend("/__promises", { user: me.id, plan: "free", asking: [meeting],
      promises: [{ direction: "theirs", what: "Send the quote", who: "Rahul", due_on: "2026-09-30" }] })
    await page.goto("/")
    await page.getByTestId("promise-ask-input").fill("I'll send the deck")
    await page.getByTestId("promise-ask-save").click()
    await expect(page.getByTestId("promise-upgrade")).toHaveAttribute("href", "/billing?upgrade=plus")
    await page.getByTestId("today-promises").getByRole("button", { name: "Chase" }).click()
    await expect(page).toHaveURL("/")
  })

  test("Next up shows what's open with the people you're about to meet", async ({ page }) => {
    await backend("/__today", { user: me.id, extra: { events: [{ summary: "Q3 review", start: "2026-10-02T15:00:00+05:30",
      end: "2026-10-02T16:00:00+05:30", promises: [{ id: 1, direction: "mine", what: "Send the deck", who: "Priya" },
        { id: 2, direction: "theirs", what: "Share the numbers", who: "Priya" }] }] } })
    await page.goto("/")
    const prep = page.getByTestId("today-events").getByTestId("meeting-prep")
    await expect(prep).toContainText("You owe Priya: Send the deck")
    await expect(prep).toContainText("Priya owes you: Share the numbers")
  })

  test("Kept shows promises with Mark kept and Chase", async ({ page }) => {
    await backend("/__promises", { user: me.id, promises: [
      { direction: "mine", what: "Send the deck", who: "Priya", due_on: "2026-12-01" },
      { direction: "theirs", what: "Send the quote", who: "Rahul", due_on: "2026-12-02" },
    ] })
    await page.goto("/kept")
    const mine = page.locator('[data-testid^="kept-promise:"]', { hasText: "You promised Priya: Send the deck" })
    await expect(mine).toBeVisible()
    await mine.getByRole("button", { name: "Mark kept" }).click()
    await expect(page.locator(".h-kept-toast")).toContainText("Marked kept.")
    const theirs = page.locator('[data-testid^="kept-promise:"]', { hasText: "Rahul promised you: Send the quote" })
    await theirs.getByRole("button", { name: "Chase" }).click()
    await expect(page).toHaveURL(/\/chat/)
  })

  test("Settings can stop Hangul reading email for promises", async ({ page }) => {
    await page.goto("/settings")
    const toggle = page.getByTestId("promise-email-toggle")
    await expect(toggle).toBeChecked()
    await toggle.click()
    await expect.poll(async () => (await backendState() as unknown as { promiseEmailOn: Record<string, boolean> }).promiseEmailOn[me.id]).toBe(false)
  })
})
