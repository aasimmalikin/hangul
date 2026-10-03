import { test, expect } from "@playwright/test"
import { backend, freshUser, resetBackend, signInAs } from "./helpers"

/** "Before you go": ask why, offer one fitting alternative, keep "Cancel anyway" one click, and allow undo. */
test.describe("cancel flow", () => {
  const me = freshUser("cancel")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("Pro, too expensive: switching to Plus is offered and works", async ({ page }) => {
    await backend("/__billing", { user: me.id, plan: "pro" })
    await page.goto("/billing")
    await page.getByTestId("cancel-plan").click()
    await page.getByRole("button", { name: "It's too expensive" }).click()
    await expect(page.getByTestId("cancel-offer")).toContainText("Switch to Plus instead")
    await page.getByTestId("cancel-offer-cta").click()
    await expect(page.getByTestId("billing-notice")).toContainText("you're on Plus now")
    expect((await backend("/__state")).churn).toEqual([{ user: me.id, plan: "pro", reason: "too_expensive", detail: "", outcome: "downgraded" }])
  })

  test("cancel anyway is one click, keeps the plan to the end, and can be undone", async ({ page }) => {
    await backend("/__billing", { user: me.id, plan: "plus" })
    await page.goto("/billing")
    await page.getByTestId("cancel-plan").click()
    await page.getByRole("button", { name: "It's missing something I need" }).click()
    await page.getByLabel("Tell us more").fill("WhatsApp reminders")
    await page.getByTestId("cancel-confirm").click()
    await expect(page.getByTestId("billing-notice")).toContainText("You keep Plus until")
    await expect(page.getByTestId("plan-ending")).toContainText("ends on")
    expect((await backend("/__state")).churn[0]).toMatchObject({ reason: "missing_feature", detail: "WhatsApp reminders", outcome: "cancelled" })

    await page.getByTestId("resume-plan").click()
    await expect(page.getByTestId("billing-notice")).toContainText("You're staying")
    await expect(page.getByTestId("cancel-plan")).toBeVisible()
  })

  test("free users don't see Cancel plan", async ({ page }) => {
    await page.goto("/billing")
    await expect(page.getByTestId("allowance")).toBeVisible()
    await expect(page.getByTestId("cancel-plan")).toHaveCount(0)
  })
})
