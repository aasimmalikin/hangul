import { test, expect } from "@playwright/test"
import { ask, backend, expectReply, freshUser, resetBackend, signInAs } from "./helpers"

/** Launch plans: the questions, the dashboard filling in with live prices, editing the numbers, export,
 *  the estimates-only plan on Free with its upgrade, the chat card, and removing a plan. */
test.describe("launch plans", () => {
  const me = freshUser("launch")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("questions -> a plan whose live prices fill in by themselves", async ({ page }) => {
    await page.goto("/you")
    await page.getByTestId("you-launch").click()
    await expect(page).toHaveURL(/\/launch$/)
    await expect(page.getByTestId("launch-submit")).toBeDisabled()
    await page.getByTestId("launch-kind-cafe").click()
    await page.getByTestId("launch-size-small").click()
    await page.getByTestId("launch-city").fill("Srinagar")
    await page.getByTestId("launch-area").fill("Rajbagh")
    await page.getByTestId("launch-budget").fill("20,00,000")
    await page.getByTestId("launch-submit").click()

    await expect(page).toHaveURL(/\/launch\/9\d\d$/)
    await expect(page.getByTestId("launch-title")).toHaveText("Café in Rajbagh, Srinagar")
    await expect(page.getByTestId("launch-progress")).toContainText("Finding prices and sellers")
    // the poll picks up the finished search
    await expect(page.getByTestId("launch-progress")).toBeHidden({ timeout: 10_000 })
    const esp = page.getByTestId("launch-item-espresso")
    await expect(esp).toContainText("Sourced")
    await expect(esp.getByRole("link", { name: /Coffee Kit India/ })).toHaveAttribute("href", "https://shop.example/espresso")
    await expect(page.getByTestId("launch-suppliers")).toContainText("Valley Coffee Supplies")
    await expect(page.getByTestId("launch-benchmarks")).toContainText("28-32%")
    await expect(page.getByTestId("launch-startup")).toContainText("under your budget")
    await expect(page.getByTestId("launch-breakeven")).toBeVisible()
    await expect(page.getByTestId("launch-startup-bars")).toBeVisible()
  })

  test("editing an assumption or an item recomputes the numbers", async ({ page }) => {
    await page.goto("/launch")
    await page.getByTestId("launch-kind-cafe").click()
    await page.getByTestId("launch-size-small").click()
    await page.getByTestId("launch-city").fill("Pune")
    await page.getByTestId("launch-submit").click()
    await expect(page.getByTestId("launch-progress")).toBeHidden({ timeout: 10_000 })

    const profit = page.getByTestId("launch-profit")
    const before = await profit.textContent()
    await page.getByTestId("launch-price").fill("500")
    await page.getByTestId("launch-price").press("Enter")
    await expect(profit).not.toHaveText(before!)

    await page.getByTestId("launch-amount-furniture").fill("50000")
    await page.getByTestId("launch-amount-furniture").press("Enter")
    await expect(page.getByTestId("launch-item-furniture")).toContainText("Your number")

    const pdf = await page.getByTestId("launch-export-pdf").getAttribute("href")
    const res = await page.request.get(pdf!)
    expect(res.status()).toBe(200)
    expect(res.headers()["content-disposition"]).toContain("attachment")
  })

  test("on Free the plan uses estimates and offers the upgrade", async ({ page }) => {
    await backend("/__launch", { user: me.id, access: { allowed: false, reason: "plan_required", plan_needed: "plus",
      detail: "Live prices and sellers are part of the Plus and Pro plans." } })
    await page.goto("/launch")
    await expect(page.getByTestId("launch-access-note")).toContainText("Plus and Pro")
    await page.getByTestId("launch-kind-cafe").click()
    await page.getByTestId("launch-size-home").click()
    await page.getByTestId("launch-city").fill("Srinagar")
    await page.getByTestId("launch-submit").click()
    await expect(page.getByTestId("launch-estimates")).toBeVisible()
    await expect(page.getByTestId("launch-item-espresso")).toContainText("Estimate")
    await page.getByTestId("launch-source").click()
    const notice = page.getByTestId("launch-notice")
    await expect(notice).toContainText("Plus and Pro")
    await expect(notice.getByRole("link", { name: "See Plus" })).toHaveAttribute("href", "/billing?upgrade=plus")
  })

  test("from chat: a card that opens the plan", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "LAUNCH I want to open a café in Srinagar")
    await expectReply(page, "Your plan is on its way.")
    const card = page.getByTestId("card-launch-plan")
    await expect(card).toContainText("Café in Srinagar")
    await expect(card).toContainText("41 bills/day")
    await expect(card.getByTestId("launch-card-open")).toHaveAttribute("href", "/launch/900")
  })

  test("plans are listed and can be removed", async ({ page }) => {
    await page.goto("/launch")
    await page.getByTestId("launch-kind-cloud_kitchen").click()
    await page.getByTestId("launch-size-small").click()
    await page.getByTestId("launch-city").fill("Srinagar")
    await page.getByTestId("launch-submit").click()
    await expect(page.getByTestId("launch-title")).toBeVisible()
    await page.goto("/launch")
    await expect(page.getByTestId("launch-card")).toHaveCount(1)
    await page.getByTestId("launch-remove").click()
    await page.getByTestId("launch-remove-confirm").click()
    await expect(page.getByTestId("launch-card")).toHaveCount(0)
    await expect(page.getByTestId("launch-form")).toBeVisible()
  })
})
