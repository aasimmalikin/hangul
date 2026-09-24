import { test, expect } from "@playwright/test"
import { alice, ask, backend, signInAs } from "./helpers"

/** Workspace results render as Google-styled cards; a send shows a compose preview before approval. */
test.describe("google cards", () => {
  test.beforeEach(async () => { await backend("/__reset", {}) })

  test("gmail search renders an inbox-style list and a send waits for approval with a compose preview", async ({ page, context, baseURL }) => {
    await signInAs(context, alice, baseURL!)
    await page.goto("/chat")
    await ask(page, "GMAIL reply to alice")
    const list = page.getByTestId("gmail-list")
    await expect(list).toBeVisible()
    await expect(list).toContainText("2 messages · newer_than:1d")
    await expect(list.locator(".g-row").first()).toHaveClass(/is-unread/)
    await expect(list.locator(".g-row").first()).toContainText("Alice Example")
    await expect(list.locator(".g-row").first()).toContainText("Lunch tomorrow?")
    await expect(list.locator(".g-row").nth(1)).toContainText("updates")           // CATEGORY_ label chip

    const card = page.getByTestId("approval-card")
    await expect(card).toContainText("This email will be SENT")
    const compose = card.getByTestId("gmail-compose-pending")
    await expect(compose).toContainText("alice@example.com")
    await expect(compose).toContainText("Re: Lunch tomorrow?")
    await expect(compose).toContainText("Noon works, see you there.")
    await expect(page.locator("body")).not.toContainText("Sent an email")
    await card.getByRole("button", { name: "Approve" }).click()
    await expect(page.getByTestId("approval-card")).toHaveCount(0)
    const state = await backend("/__state")
    expect(Object.values(state.executed)).toEqual([1])
  })
})
