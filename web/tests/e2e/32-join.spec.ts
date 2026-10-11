import { test, expect } from "@playwright/test"
import { backend } from "./helpers"

/**
 * Pre-registration (/join): open without an account, remembers where the
 * visitor came from, answers the same for a repeat email, and only shows the
 * count once it's worth showing.
 */
test.describe("pre-registration", () => {
  test.beforeEach(async () => { await backend("/__reset", {}) })

  test("join from a link on X with your business, city and the plan you want", async ({ page }) => {
    await page.goto("/join?ref=x")
    await page.getByTestId("join-email").fill("Priya@Example.com")
    await page.getByTestId("join-trade-cafe").click()
    await page.getByTestId("join-city").fill("Pune")
    await page.getByTestId("join-plan-pro").click()
    await page.getByTestId("join-submit").click()
    await expect(page.getByTestId("join-done")).toContainText("You're on the list")
    await expect(page.getByTestId("join-share")).toHaveAttribute("href", /x\.com\/intent\/post/)
    const s = await backend("/__state") as { waitlist: Record<string, string>[] }
    expect(s.waitlist).toEqual([{ email: "priya@example.com", trade: "cafe", city: "Pune", persona: "", interest: "pro", source: "x" }])
  })

  test("joining twice looks the same and adds no second row", async ({ page }) => {
    for (let i = 0; i < 2; i++) {
      await page.goto("/join")
      await page.getByTestId("join-email").fill("sam@example.com")
      await page.getByTestId("join-submit").click()
      await expect(page.getByTestId("join-done")).toBeVisible()
    }
    const s = await backend("/__state") as { waitlist: unknown[] }
    expect(s.waitlist).toHaveLength(1)
  })

  test("a bad email is explained, not swallowed", async ({ page }) => {
    await page.goto("/join")
    // the browser's own check is skipped so the server's message is what shows
    await page.getByTestId("join-form").evaluate((f) => f.setAttribute("novalidate", ""))
    await page.getByTestId("join-email").fill("me@nowhere")
    await page.getByTestId("join-submit").click()
    await expect(page.getByTestId("join-error")).toContainText("email address")
    await expect(page.getByTestId("join-done")).toHaveCount(0)
  })

  test("the count only shows once it is worth showing", async ({ page }) => {
    await backend("/__waitlist", { base: 12 })
    await page.goto("/join")
    await expect(page.getByTestId("join-form")).toBeVisible()
    await expect(page.getByTestId("join-count")).toHaveCount(0)

    await backend("/__waitlist", { base: 1234 })
    await page.goto("/join")
    await expect(page.getByTestId("join-count")).toContainText("1,234 people have pre-registered")
  })

  test("the privacy policy says what pre-registration keeps", async ({ page }) => {
    await page.goto("/privacy")
    await expect(page.locator("article")).toContainText("Pre-registration:")
  })
})
