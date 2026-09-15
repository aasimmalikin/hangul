import { test, expect } from "@playwright/test"
import { alice, signInAs } from "./helpers"

test.describe("sign-in gate", () => {
  test("signed out: sending, + and ?q= all open the sign-in modal, nothing is sent", async ({ page, request }) => {
    await page.goto("/chat")
    await page.getByPlaceholder(/Ask/).fill("hello")
    await page.keyboard.press("Enter")
    await expect(page.getByRole("dialog")).toContainText("Sign in to ask the agent")
    await page.keyboard.press("Escape")
    await page.locator(".h-scrim").click({ position: { x: 5, y: 5 } })

    await page.getByRole("button", { name: "Add" }).click()
    await expect(page.getByRole("dialog")).toContainText("add a document")
    await page.locator(".h-scrim").click({ position: { x: 5, y: 5 } })

    await page.goto("/chat?q=First+question")
    await expect(page.getByRole("dialog")).toBeVisible()

    const state = await (await request.get("http://127.0.0.1:8765/__state")).json()
    expect(state.asks).toHaveLength(0)
  })

  test("landing: Sign up opens the sign-up copy, Sign in the sign-in copy", async ({ page }) => {
    await page.goto("/")
    await page.getByRole("button", { name: "Sign up" }).click()
    await expect(page.getByRole("dialog")).toContainText("Create your account")
    await expect(page.getByRole("dialog")).toContainText("Sign up with Google")
    await page.locator(".h-scrim").click({ position: { x: 5, y: 5 } })
    await page.getByRole("button", { name: "Sign in", exact: true }).click()
    await expect(page.getByRole("dialog")).toContainText("Sign in to continue")
  })

  test("signed in: header shows avatar menu with sign out and quality", async ({ page, context, baseURL }) => {
    await signInAs(context, alice, baseURL!)
    await page.goto("/chat")
    await page.getByRole("button", { name: "Account menu" }).click()
    await expect(page.getByText(alice.email)).toBeVisible()
    await expect(page.getByRole("button", { name: /Sign out/ })).toBeVisible()
    await expect(page.getByTestId("quality-row")).toContainText("gate passed")
    await expect(page.getByTestId("quality-row")).toContainText("Correct 91%")
  })

  test("session expires mid-conversation: modal explains, thread is kept", async ({ page, context, baseURL }) => {
    await signInAs(context, alice, baseURL!)
    await page.goto("/chat")
    await page.getByPlaceholder(/Ask/).fill("hello")
    await page.keyboard.press("Enter")
    await expect(page.getByTestId("run-done")).toBeAttached()

    await page.waitForLoadState("networkidle")
    await context.clearCookies() // cookie expired / revoked
    await page.getByPlaceholder(/Ask/).fill("still there?")
    await page.keyboard.press("Enter")
    await expect(page.getByRole("dialog")).toContainText("session has expired")
    await expect(page.locator(".h-prose").first()).toContainText("hello")
  })
})
