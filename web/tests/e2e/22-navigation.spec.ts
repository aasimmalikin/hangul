import { test, expect } from "@playwright/test"
import { freshUser, resetBackend, seedChat, signInAs } from "./helpers"

/** The places (direction A): Today, Chats, Business, Customers, Kept and You as header tabs on desktop;
 *  five of them (no Kept, which is under You) in the bottom bar on phones. */
test.describe("navigation", () => {
  const me = freshUser("nav")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("desktop: header tabs mark where you are", async ({ page }) => {
    await page.goto("/kept")
    await expect(page.getByTestId("nav-Kept")).toHaveAttribute("aria-current", "page")
    await page.getByTestId("nav-You").click()
    await expect(page).toHaveURL(/\/you$/)
    await expect(page.getByTestId("you-preferences")).toContainText("Profile & preferences")
    await expect(page.getByTestId("you-apps")).toContainText("Connected apps")
    await expect(page.getByTestId("you-plan")).toContainText("Plan & billing")
    await page.getByTestId("you-apps").click()
    await expect(page.getByRole("heading", { name: "Connected apps" })).toBeVisible()
    await expect(page.getByTestId("nav-You")).toHaveAttribute("aria-current", "page")     // still under "You"
  })

  test("the old /lists address opens Kept's drawer, with files to download", async ({ page }) => {
    await page.goto("/lists")
    await expect(page).toHaveURL(/\/kept#holding$/)
    await expect(page.getByRole("heading", { name: "Kept" })).toBeVisible()
    await expect(page.getByTestId("files-section")).toContainText("monthly-budget.pdf")
    await expect(page.getByRole("link", { name: "Download monthly-budget.pdf" })).toHaveAttribute("href", "/api/files/monthly-budget.pdf")
  })

  test.describe("on a phone", () => {
    test.use({ viewport: { width: 390, height: 844 } })

    test("bottom bar on Today, hidden inside a chat; Chats lists conversations", async ({ page }) => {
      await seedChat(me, "Trip to Goa")
      await page.goto("/")
      const bar = page.locator(".h-bottom-nav")
      await expect(bar).toBeVisible()
      await expect(bar.getByRole("link", { name: "Today" })).toHaveAttribute("aria-current", "page")
      await bar.getByRole("link", { name: "Chats" }).click()
      await expect(page).toHaveURL(/\/chats$/)
      await expect(page.getByTestId("chats-panel")).toContainText("Trip to Goa")          // the rail is hidden on phones; this isn't
      await page.getByRole("button", { name: "New chat" }).click()
      await expect(page).toHaveURL(/\/chat$/)
      await expect(page.locator(".h-bottom-nav")).toHaveCount(0)                           // the composer owns the bottom
    })
  })
})
