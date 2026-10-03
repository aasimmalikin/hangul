import { test, expect } from "@playwright/test"
import { ask, expectReply, freshUser, resetBackend, signInAs } from "./helpers"

/** Phase 3: a created file downloads, a chart and its table render, and a Free user sees an upgrade card. */
test.describe("productivity", () => {
  const me = freshUser("productivity")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("a created file has a working download", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "REPORT make my budget a PDF")
    const card = page.getByTestId("card-file")
    await expect(card).toContainText("monthly-budget.pdf")
    await expect(card).toContainText("PDF")
    const href = await card.getByTestId("file-download").getAttribute("href")
    const res = await page.request.get(href!)
    expect(res.status()).toBe(200)
    expect(res.headers()["content-disposition"]).toContain("attachment")
    expect((await res.body()).subarray(0, 4).toString()).toBe("%PDF")
  })

  test("a chart is shown as an image", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "CHART where did my money go")
    await expectReply(page, "Here it is.")
    const img = page.getByTestId("card-chart").locator("img")
    await expect.poll(() => img.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth)).toBeGreaterThan(0)
  })

  test("a Free user gets an upgrade card", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "LOCKED make a PDF")
    const card = page.getByTestId("card-upgrade")
    await expect(card).toContainText("Creating files")
    await expect(card.getByRole("link", { name: "Upgrade to Plus" })).toHaveAttribute("href", "/billing?upgrade=plus")
  })
})
