import { test, expect } from "@playwright/test"
import { freshUser, ask, backendState, expectReply, resetBackend, signInAs } from "./helpers"

test.describe("human in the loop", () => {
  const me = freshUser("human")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("the file content is shown as it is drafted, then in full on the approval card", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "APPROVAL show me first")
    // while the model writes the call: row says it is drafting, content streams in
    const row = page.getByTestId("tool-row")
    await expect(row).toHaveAttribute("data-status", "pending")
    await expect(row).toContainText("Drafting a file")
    await expect(page.getByTestId("tool-draft")).toContainText("Line one")
    // once parked for approval: row is explicit that nothing ran yet
    await expect(row).toHaveAttribute("data-status", "awaiting")
    await expect(row).toContainText("Wants to write a file")
    await expect(row).toContainText("needs your approval")
    await expect(page.locator("body")).not.toContainText("Wrote a file")
    // the card lays out exactly what will happen
    const card = page.getByTestId("approval-card")
    await expect(card).toContainText("Approve this action?")
    await expect(card).toContainText("notes.txt")
    await expect(card.getByTestId("approval-content")).toContainText("Line three closes it.")
    await expect(card).toContainText("Nothing has been changed yet")
  })

  test("thinking indicator shows the step while the model is deciding", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "SLOW deciding")
    await expect(page.getByTestId("thinking")).toContainText("Thinking")
    await expect(page.getByTestId("thinking")).toContainText("step 1")
    await expectReply(page, "Reply to: SLOW deciding")
    await expect(page.getByTestId("thinking")).toHaveCount(0)
  })

  test("approve a destructive tool; a double-click executes it once", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "APPROVAL write my notes")
    const card = page.getByTestId("approval-card")
    await expect(card).toContainText("write file")
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
