import { test, expect } from "@playwright/test"
import { freshUser, ask, expectReply, resetBackend, signInAs } from "./helpers"

test.describe("activity block", () => {
  const me = freshUser("activity")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("while working: one live line with the breathing sigil; when done: one folded summary that expands", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "SLOW plan the rollout")
    // live: a single block, sigil animating, current step shimmering
    const live = page.getByTestId("activity")
    await expect(live).toHaveCount(1)
    await expect(live).toHaveAttribute("data-live", "true")
    await expect(live.locator(".h-sigil-live")).toHaveCount(1)
    await expect(live.locator(".h-shimmer")).toContainText("Thinking")
    await expect(live.locator(".h-sigil-live")).toHaveCSS("animation-name", "h-breathe")
    await expect(live.getByTestId("thinking")).toContainText("step 1")

    await expectReply(page, "Reply to: SLOW plan the rollout")
    // done: still one block, folded, summarising the work in one line
    const done = page.getByTestId("activity")
    await expect(done).toHaveCount(1)
    await expect(done).toHaveAttribute("data-live", "false")
    await expect(done).toHaveAttribute("data-open", "false")
    await expect(done.getByTestId("activity-rows")).toHaveCount(0)
    await expect(done.locator(".h-activity-head")).toContainText("Searched your documents")
    await expect(done.locator(".h-sigil-live")).toHaveCount(0)
    await expect(page.getByTestId("thinking")).toHaveCount(0)
    // the rows are one click away
    await done.locator(".h-activity-head").click()
    await expect(done).toHaveAttribute("data-open", "true")
    await expect(done.getByTestId("tool-row")).toHaveCount(1)
    await expect(done.getByTestId("tool-row")).toHaveAttribute("data-status", "done")
    await done.locator(".h-activity-head").click()
    await expect(done.getByTestId("activity-rows")).toHaveCount(0)
  })

  test("a run that needs the user unfolds by itself (drafted file, approval)", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "APPROVAL write my notes")
    await expect(page.getByTestId("approval-card")).toBeVisible()
    const block = page.getByTestId("activity")
    await expect(block).toHaveAttribute("data-open", "true")
    await expect(block.getByTestId("tool-row")).toHaveAttribute("data-status", "awaiting")
    await expect(block).toContainText("needs your approval")
  })

  test("several runs each fold into their own block; the thread does not fill with rows", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "one")
    await expectReply(page, "Reply to: one")
    await ask(page, "two")
    await expectReply(page, "Reply to: two")
    await expect(page.getByTestId("activity")).toHaveCount(2)
    await expect(page.getByTestId("tool-row")).toHaveCount(0)   // all folded
    for (const b of await page.getByTestId("activity").all()) await expect(b).toHaveAttribute("data-open", "false")
  })
})
