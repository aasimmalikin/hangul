import { test, expect } from "@playwright/test"
import { ask, backend, expectReply, freshUser, resetBackend, signInAs } from "./helpers"

/** How's business: setting up, logging today, importing past sales, tomorrow's forecast with its reasons, a slow
 *  day's idea opening Brand Studio with the post filled in, the Free / Plus / Pro split, and the chat cards.
 *  The fake serves the real overview (business-fixture.json, from make_fixtures.py). */
const CSV = Buffer.from('Date,Orders,Net Sales\n13/09/2026,40,"12,400"\n14/09/2026,35,"10,050"\n')

test.describe("how's business", () => {
  const me = freshUser("business")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("set up, log today, import the past, and see tomorrow", async ({ page }) => {
    await page.goto("/you")
    await page.getByTestId("you-business").click()
    await expect(page).toHaveURL(/\/business$/)
    await page.getByTestId("biz-name").fill("Chinar Café")
    await page.getByTestId("biz-city").fill("Srinagar")
    await page.getByTestId("biz-kind-cafe").click()
    await page.getByTestId("biz-save").click()

    await expect(page.getByTestId("biz-learning")).toContainText("0 of 14 days")
    await page.getByTestId("biz-sales").fill("16,400")
    await page.getByTestId("biz-bills").fill("52")
    await page.getByTestId("biz-log-save").click()
    await expect(page.getByTestId("biz-logged")).toContainText("₹16,400 · 52 bills")
    await expect(page.getByTestId("biz-learning")).toContainText("1 of 14 days")

    await page.getByTestId("biz-import-file").setInputFiles({ name: "petpooja.csv", mimeType: "text/csv", buffer: CSV })
    await expect(page.getByTestId("biz-import-preview")).toContainText("90 days found")
    await expect(page.getByTestId("biz-import-preview")).toContainText("Net Sales")
    await page.getByTestId("biz-import-save").click()
    await expect(page.getByTestId("biz-import-msg")).toContainText("Added 90 days")

    const tomorrow = page.getByTestId("biz-tomorrow")
    await expect(tomorrow.getByTestId("biz-forecast")).toContainText("₹9,777")
    await expect(tomorrow.getByTestId("biz-slow")).toBeVisible()
    await expect(tomorrow.getByTestId("biz-reasons")).toContainText("Rain is likely")
    await expect(tomorrow.getByTestId("biz-accuracy")).toContainText("within 6%")
    await expect(page.getByTestId("business-chart")).toBeVisible()
  })

  test("a slow day's idea opens Brand Studio with the post filled in", async ({ page }) => {
    await backend("/__brands", { user: me.id, brands: [{ name: "Chinar Café" }] })
    await backend("/__business", { user: me.id, seeded: true })
    await page.goto("/business")
    const ideas = page.getByTestId("biz-ideas")
    await expect(ideas.getByTestId("biz-idea-rain_offer")).toContainText("A rainy-day offer")
    await expect(ideas.getByTestId("biz-idea-rain_offer")).toContainText("each sale still leaves about")
    await ideas.getByTestId("biz-make-rain_offer").click()
    await expect(page).toHaveURL(/\/brands\/200\?tab=create&layout=offer/)
    await expect(page.getByTestId("studio-from-business")).toBeVisible()
    await expect(page.getByTestId("word-headline")).toHaveValue("Rainy day? We deliver")
    await expect(page.getByTestId("word-price")).toHaveValue("10% OFF")
  })

  test("Plus sees the forecast and one idea a week, not why", async ({ page }) => {
    await backend("/__business", { user: me.id, seeded: true, plan: "plus" })
    await page.goto("/business")
    await expect(page.getByTestId("biz-forecast")).toContainText("₹9,777")
    await expect(page.getByTestId("biz-reasons")).toHaveCount(0)
    await expect(page.getByTestId("biz-tomorrow").getByTestId("biz-locked-pro")).toContainText("Why tomorrow looks this way")
    await expect(page.getByTestId("biz-ideas").locator("article")).toHaveCount(1)
    await expect(page.getByTestId("biz-ideas").getByTestId("biz-locked-pro")).toContainText("An idea for every slow day")
  })

  test("Free logs and sees the week; the forecast is Plus", async ({ page }) => {
    await backend("/__business", { user: me.id, seeded: true, plan: "free" })
    await page.goto("/business")
    await expect(page.getByTestId("biz-week")).toBeVisible()
    await expect(page.getByTestId("biz-locked-plus")).toContainText("Tomorrow's sales forecast")
    await expect(page.getByTestId("biz-forecast")).toHaveCount(0)
    await expect(page.getByTestId("biz-locked-plus").getByRole("link")).toHaveAttribute("href", "/billing?upgrade=plus")
  })

  test("from chat: logging and tomorrow's forecast", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "SALES today 52 bills, 16,400")
    await expectReply(page, "Logged ₹16,400")
    await expect(page.getByTestId("card-sales-logged")).toContainText("₹16,400")
    await ask(page, "FORECAST how will tomorrow be?")
    await expectReply(page, "Tomorrow looks slow.")
    const card = page.getByTestId("card-sales-forecast")
    await expect(card).toContainText("₹9,777")
    await expect(card).toContainText("Looks slow")
    await expect(card.getByTestId("sales-card-open")).toHaveAttribute("href", "/business")
  })
})
