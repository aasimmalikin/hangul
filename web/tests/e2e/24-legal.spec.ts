import { test, expect } from "@playwright/test"

/** Terms, Privacy and Refunds are public, linked where people sign in and pay, and say what Google's review needs. */
test.describe("legal pages", () => {
  test("all three load without signing in", async ({ page }) => {
    for (const [path, title] of [["/terms", "Terms of Service"], ["/privacy", "Privacy Policy"], ["/refunds", "Refund Policy"]]) {
      await page.goto(path)
      await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible()
    }
  })

  test("privacy policy has Google's Limited Use statement and the honest bits", async ({ page }) => {
    await page.goto("/privacy")
    await expect(page.locator("article")).toContainText("Limited Use requirements")
    await expect(page.locator("article")).toContainText("is not stored")                       // voice recordings
    await expect(page.locator("article")).toContainText("a copy stays in our database")        // what "delete chat" means today
    await expect(page.locator("article")).toContainText("never see or store your card details")
  })

  test("placeholders are flagged until filled in", async ({ page }) => {
    await page.goto("/terms")
    await expect(page.getByTestId("legal-draft")).toBeVisible()
  })

  test("signing in shows the agreement, the home page links them", async ({ page }) => {
    await page.goto("/")
    await expect(page.getByTestId("landing-legal").getByRole("link", { name: "Privacy" })).toHaveAttribute("href", "/privacy")
    await page.getByRole("button", { name: "Sign in" }).first().click()
    await expect(page.getByTestId("signin-legal").getByRole("link", { name: "Terms" })).toHaveAttribute("href", "/terms")
  })
})
