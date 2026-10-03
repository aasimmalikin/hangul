import { test, expect } from "@playwright/test"
import { ask, backend, freshUser, openOptions, resetBackend, signInAs } from "./helpers"

/** Paid model access (harness.billing): plan refusals become an upgrade card, locked models show in the picker, /billing starts a checkout. */
test.describe("billing", () => {
  const me = freshUser("billing")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("a plan refusal shows an upgrade card, not the error notice", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "PAYWALL use the big model")
    const card = page.getByTestId("upgrade-card")
    await expect(card).toBeVisible()
    await expect(card).toHaveAttribute("data-code", "plan_required")
    await expect(card).toContainText("needs the Plus plan")
    await expect(page.getByTestId("notice-card")).toHaveCount(0)
    await page.getByTestId("upgrade-link").click()
    await expect(page).toHaveURL(/\/billing\?upgrade=plus/)
    await expect(page.getByTestId("plan-plus")).toBeVisible()
  })

  test("out of allowance offers credits too", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "BROKE one more question")
    const card = page.getByTestId("upgrade-card")
    await expect(card).toHaveAttribute("data-code", "insufficient_balance")
    await expect(card.getByRole("link", { name: "Buy credits" })).toBeVisible()
  })

  test("a full free pool offers upgrade and credits", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "FULL one more free question")
    const card = page.getByTestId("upgrade-card")
    await expect(card).toHaveAttribute("data-code", "free_pool_exhausted")
    await expect(card).toContainText("Free capacity is full")
    await expect(card.getByTestId("upgrade-link")).toBeVisible()
    await expect(card.getByRole("link", { name: "Buy credits" })).toBeVisible()
  })

  test("locked models are badged and lead to the upgrade page", async ({ page }) => {
    await page.goto("/chat")
    await openOptions(page)
    await page.getByTestId("model-picker").click()
    await expect(page.getByTestId("model-option-fake-frontier-locked")).toContainText("Pro")
    await expect(page.getByTestId("model-option-fake-plain-locked")).toHaveCount(0)
    await page.getByTestId("model-option-fake-frontier").click()
    await expect(page).toHaveURL(/\/billing\?upgrade=pro/)
  })

  test("the billing page shows the allowance and starts a checkout", async ({ page }) => {
    await page.goto("/billing")
    await expect(page.getByTestId("allowance")).toContainText("$0.20 of $0.50 left")
    await expect(page.getByTestId("credits")).toHaveText("$1.50")
    await page.getByTestId("upgrade-plus").click()
    await expect(page).toHaveURL(/\/billing\?checkout=plus/)
    const s = await backend("/__state")
    expect(s.checkouts).toEqual([{ user: me.id, product: "plus" }])
  })

  test("manage subscription opens the provider portal", async ({ page }) => {
    await page.goto("/billing")
    await page.getByTestId("manage-subscription").click()
    await expect(page).toHaveURL(/\/billing\?portal=1/)
  })
})
