import { test, expect } from "@playwright/test"
import { backend, freshUser, resetBackend, signInAs } from "./helpers"

/** Customers: adding regulars, searching, "came in today", removing, and the birthday and win-back panels
 *  (which only open the chat to draft a message: Hangul never messages a customer itself). */
test.describe("customers", () => {
  const me = freshUser("customers")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("add a customer from /you, note a visit, search and remove", async ({ page }) => {
    await page.goto("/you")
    await page.getByTestId("you-customers").click()
    await expect(page).toHaveURL(/\/customers$/)
    await expect(page.getByTestId("customers-empty")).toBeVisible()

    await page.getByTestId("customer-name").fill("Riya")
    await page.getByTestId("customer-phone").fill("98765 43210")
    await page.getByTestId("customer-note").fill("likes masala chai")
    await page.getByTestId("customer-add").click()
    const row = page.getByTestId("customer-row")
    await expect(row).toHaveCount(1)
    await expect(row).toContainText("+919876543210")
    await expect(row).toContainText("likes masala chai")

    await row.getByTestId("customer-visit").click()
    await expect(row.getByTestId("customer-visit")).toHaveText("Here today")
    await expect(row).toContainText("1 visit, today")

    await page.getByTestId("customer-search").fill("nobody")
    await expect(page.getByTestId("customers-empty")).toHaveText("Nobody matches.")
    await page.getByTestId("customer-search").fill("")
    await row.getByTestId("customer-remove").click()
    await expect(page.getByTestId("customer-row")).toHaveCount(0)
  })

  test("birthdays and regulars who stopped coming open the chat to draft a message", async ({ page }) => {
    await backend("/__customers", { user: me.id, customers: [
      { id: 801, name: "Aman", phone: "+919800000001", birthday: "10-12", note: "", visits: 2, last_visit: "2026-10-01" },
      { id: 802, name: "Sana", phone: "", birthday: null, note: "", visits: 6, last_visit: "2026-08-20" },
    ] })
    await page.goto("/customers")
    await expect(page.getByTestId("customers-birthdays")).toContainText("Aman")
    await expect(page.getByTestId("customers-lapsed")).toContainText("Sana")
    await page.getByTestId("customers-lapsed").getByRole("button", { name: "Win back" }).click()
    await expect(page).toHaveURL(/\/chat\?q=Draft%20a%20short%2C%20friendly/)
  })
})
