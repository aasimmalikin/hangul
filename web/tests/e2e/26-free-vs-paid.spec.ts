import { test, expect } from "@playwright/test"
import { backend, freshUser, resetBackend, signInAs } from "./helpers"

/** Free vs paid: usage shown as messages, the Plus trial, and the 80% "running low" nudge in the chat. */
test.describe("free vs paid", () => {
  const me = freshUser("plans")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("usage is shown as messages and Plus offers a free trial", async ({ page }) => {
    await backend("/__billing", { user: me.id, extra: { messages_left: 20, messages_total: 25, trial_days: 7 } })
    await page.goto("/billing")
    await expect(page.getByTestId("messages-left")).toContainText("About 20 of 25 messages left")
    // $0.50 for 25 messages = $0.02 each, so Plus's $8 is about 400
    await expect(page.getByTestId("plan-plus")).toContainText("About 400 messages a month")
    await expect(page.getByTestId("upgrade-plus")).toHaveText("Start 7-day free trial")
    await expect(page.getByTestId("trial-note")).toContainText("Nothing is charged until the trial ends")
    await expect(page.getByTestId("upgrade-pro")).toHaveText("Upgrade to Pro")
  })

  test("a trial says when it ends", async ({ page }) => {
    await backend("/__billing", { user: me.id, plan: "plus",
      extra: { status: "trialing", trialing: true, trial_ends_at: "2026-10-10T00:00:00Z", messages_left: 180, messages_total: 200 } })
    await page.goto("/billing")
    await expect(page.getByText(/Free trial — ends .+, then \$20\/month unless you cancel\./)).toBeVisible()
    await expect(page.getByTestId("allowance")).toContainText("Included in your trial")
  })

  test("running low shows a dismissible nudge in the chat", async ({ page }) => {
    await backend("/__billing", { user: me.id, extra: { nudge: true, messages_left: 3, messages_total: 25, trial_days: 7 } })
    await page.goto("/chat")
    const nudge = page.getByTestId("usage-nudge")
    await expect(nudge).toContainText("about 3 left")
    await expect(page.getByTestId("usage-nudge-upgrade")).toHaveText("Start 7-day free trial")
    await expect(page.getByTestId("usage-nudge-upgrade")).toHaveAttribute("href", "/billing?upgrade=plus")
    await page.getByTestId("usage-nudge-dismiss").click()
    await expect(nudge).toHaveCount(0)
    await page.reload()
    await expect(page.getByTestId("composer-input").or(page.locator("textarea")).first()).toBeVisible()
    await expect(page.getByTestId("usage-nudge")).toHaveCount(0)      // stays dismissed in this tab
  })

  test("no nudge while there is plenty left", async ({ page }) => {
    await backend("/__billing", { user: me.id, extra: { nudge: false, messages_left: 20, messages_total: 25 } })
    await page.goto("/chat")
    await expect(page.locator("textarea").first()).toBeVisible()
    await expect(page.getByTestId("usage-nudge")).toHaveCount(0)
  })
})
