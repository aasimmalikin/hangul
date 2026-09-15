import { test, expect } from "@playwright/test"
import { freshUser, ask, backendState, resetBackend, signInAs } from "./helpers"

test.describe("human in the loop", () => {
  const me = freshUser("human")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("approve a destructive tool; a double-click executes it once", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "APPROVAL write my notes")
    const card = page.getByTestId("approval-card")
    await expect(card).toContainText("filesystem__write_file")
    // two clicks in quick succession — the second must not fire a second approve
    await card.getByRole("button", { name: "Approve" }).dblclick()
    await expect(page.locator(".h-prose").last()).toContainText("Wrote notes.txt.")
    const s = await backendState()
    expect(Object.values(s.executed)).toEqual([1])
  })

  test("reject a destructive tool", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "APPROVAL delete stuff")
    await page.getByTestId("approval-card").getByRole("button", { name: "Reject" }).click()
    await expect(page.locator(".h-prose").last()).toContainText("won't write")
  })

  test("clarifying question renders options; the choice resumes the run", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "ASK me something")
    const card = page.getByTestId("choice-card")
    await expect(card).toContainText("Which format?")
    await card.getByRole("button", { name: "Markdown" }).click()
    await expect(page.locator(".h-prose").last()).toContainText("You chose Markdown.")
  })

  test("an approval already handled is refused, not re-run", async ({ page, context }) => {
    await page.goto("/chat")
    await ask(page, "APPROVAL once only")
    await page.getByTestId("approval-card").getByRole("button", { name: "Approve" }).click()
    await expect(page.locator(".h-prose").last()).toContainText("Wrote notes.txt.")
    const s = await backendState()
    expect(Object.values(s.executed)).toEqual([1])
    // a client that somehow still holds the old card gets "not found", not a second run
    const runId = Object.keys(s.executed)[0]
    const res = await context.request.post("/api/approve", { headers: { "Sec-Fetch-Site": "same-origin" }, data: { approval_id: runId, decision: "approve" } })
    expect(res.status()).toBe(404)
    expect(Object.values((await backendState()).executed)).toEqual([1])
  })

  test("approval survives a refresh (persisted card) and can still be decided", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "APPROVAL then refresh")
    await expect(page.getByTestId("approval-card")).toBeVisible()
    await page.reload()
    await page.getByTestId("approval-card").getByRole("button", { name: "Approve" }).click()
    await expect(page.locator(".h-prose").last()).toContainText("Wrote notes.txt.")
  })
})
