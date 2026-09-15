import { test, expect } from "@playwright/test"
import { freshUser, ask, backend, backendState, expectReply, resetBackend, signInAs } from "./helpers"

test.describe("failures", () => {
  const me = freshUser("failures")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })
  test.afterEach(async () => { await backend("/__control", { down: false }) })

  test("stream cut mid-answer: partial text kept, interrupted notice, retry works", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "DROP the line")
    await expect(page.getByTestId("notice-card")).toContainText("interrupted")
    await expect(page.locator(".h-prose").last()).toContainText("Reply to: DROP")
    // retry re-sends the same question; the fake drops again but the count shows it went
    await page.getByTestId("retry").click()
    await expect(page.getByTestId("notice-card")).toContainText("interrupted")
    expect((await backendState()).asks).toHaveLength(2)
  })

  test("agent error event is shown, not swallowed", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "ERROR please")
    await expect(page.getByTestId("notice-card")).toContainText("injected agent failure")
  })

  test("backend 500 / 429 / 401 map to honest messages", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "E500 boom")
    await expect(page.getByTestId("notice-card")).toContainText("injected 500")
    await page.getByRole("button", { name: "Dismiss" }).click()

    await ask(page, "E429 slow down")
    await expect(page.getByTestId("notice-card")).toContainText("injected 429")
    await page.getByRole("button", { name: "Dismiss" }).click()

    // A 401 from the backend is a service-token problem, not the user's session:
    // no sign-in modal, a backend-fault message instead.
    await ask(page, "E401 token")
    await expect(page.getByTestId("notice-card")).toContainText("injected 401")
    await expect(page.getByRole("dialog")).toHaveCount(0)
  })

  test("backend down: banner appears, sending fails clearly, banner clears on recovery", async ({ page }) => {
    await page.goto("/chat")
    await backend("/__control", { down: true })
    await ask(page, "anyone there?")
    await expect(page.getByTestId("notice-card")).toBeVisible()
    await expect(page.getByTestId("status-banner")).toContainText("unreachable")
    await backend("/__control", { down: false })
    await page.getByRole("button", { name: "Check now" }).click()
    await expect(page.getByTestId("status-banner")).toHaveCount(0)
    await page.getByTestId("retry").click()
    await expectReply(page, "Reply to: anyone there?")
  })

  test("browser offline: banner, send disabled; back online: works again", async ({ page, context }) => {
    await page.goto("/chat")
    await context.setOffline(true)
    await expect(page.getByTestId("status-banner")).toContainText("offline")
    await page.getByPlaceholder(/Ask/).fill("queued?")
    await expect(page.getByRole("button", { name: "Send" })).toBeDisabled()
    await context.setOffline(false)
    await expect(page.getByTestId("status-banner")).toHaveCount(0)
    await page.keyboard.press("Enter")
    await expectReply(page, "Reply to: queued?")
  })

  test("navigating away mid-answer: the question is kept, flagged as cut short, retry completes it", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "SLOW long answer")
    await expect(page.getByTestId("thinking")).toBeVisible()
    await page.goto("/") // leaves while the agent is still working; backend sees the disconnect
    await page.goBack()
    await expect(page.locator(".h-prose").first()).toContainText("SLOW long answer")
    await expect(page.getByTestId("notice-card")).toBeVisible()
    await page.getByTestId("retry").click()
    await expectReply(page, "Reply to: SLOW long answer")
    await expect(page.getByTestId("notice-card")).toHaveCount(0)
  })

  test("offline never looks like signed out", async ({ page, context }) => {
    await page.goto("/chat")
    await expect(page.getByRole("button", { name: "Account menu" })).toBeVisible()
    await context.setOffline(true)
    await expect(page.getByTestId("status-banner")).toContainText("offline")
    await page.waitForTimeout(1500)
    await expect(page.getByRole("button", { name: "Account menu" })).toBeVisible()
    await expect(page.getByRole("button", { name: "Sign in", exact: true })).toHaveCount(0)
    await context.setOffline(false)
  })
})
