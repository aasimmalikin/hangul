import { test, expect } from "@playwright/test"
import { backend, freshUser, resetBackend, signInAs } from "./helpers"

/** Design direction A ("Ledger"): the shop first on Today (today's sales, tomorrow, Log sales without the
 *  chat), and the phone's five tabs. The fake serves the real overview (business-fixture.json). */
test.describe("direction A", () => {
  const me = freshUser("ledger")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("Today leads with the shop: not logged yet, tomorrow's warning, and Log sales saves the day", async ({ page }) => {
    await backend("/__business", { user: me.id, seeded: true, plan: "pro" })
    await page.goto("/")
    const sales = page.getByTestId("shop-sales")
    await expect(sales).toContainText("Not logged yet")
    await expect(sales).toContainText("Yesterday: ₹14,049 · 45 bills")
    const tomorrow = page.getByTestId("shop-tomorrow")
    await expect(tomorrow).toContainText("Tomorrow looks slow · ↓")
    await expect(tomorrow).toContainText("About ₹9,777, under break-even")
    await expect(tomorrow).toHaveAttribute("href", "/business#ideas")

    await page.getByTestId("log-sales-fab").click()
    await page.getByTestId("log-sales-amount").fill("16,400")
    await page.getByTestId("log-sales-bills").fill("52")
    await page.getByTestId("log-sales-save").click()
    await expect(sales).toContainText("₹16,400")
    await expect(sales).toContainText("52 bills")
    await expect(sales).toContainText("over break-even")
    const state = await backend("/__state") as { business: Record<string, { days: { day: string; sales: number }[] }> }
    expect(state.business[me.id].days.find((d) => d.day === "2026-10-06")?.sales).toBe(16400)
  })

  test("with no business yet, Today asks to set one up", async ({ page }) => {
    await page.goto("/")
    await expect(page.getByTestId("shop-setup")).toContainText("Set up your shop")
    await expect(page.getByTestId("shop-setup")).toHaveAttribute("href", "/business")
  })

  test.describe("on a phone", () => {
    test.use({ viewport: { width: 390, height: 844 } })

    test("five tabs: Today, Chats, Business, Customers, You", async ({ page }) => {
      await page.goto("/")
      const bar = page.locator(".h-bottom-nav")
      await expect(bar.getByRole("link")).toHaveText(["Today", "Chats", "Business", "Customers", "You"])
      await bar.getByRole("link", { name: "Business" }).click()
      await expect(page).toHaveURL(/\/business$/)
      await expect(bar.getByRole("link", { name: "Business" })).toHaveAttribute("aria-current", "page")
      await bar.getByRole("link", { name: "Customers" }).click()
      await expect(page).toHaveURL(/\/customers$/)
    })
  })
})
