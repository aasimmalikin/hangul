import { test, expect } from "@playwright/test"
import { ask, backend, expectReply, freshUser, signInAs } from "./helpers"

/** Personalisation, scheduled tasks, deep research, and the Google Workspace bundle's connect state. */
test.describe("personal agent", () => {
  // Its own id rather than the shared `alice`: that one is fixed at 101 and used
  // by several spec files, so they share the BFF's per-user rate-limit buckets
  // and this file's /api/approve call intermittently answered 429.
  const alice = freshUser("personal")

  test.beforeEach(async () => { await backend("/__reset", {}) })

  test("settings: preferences save, a task is created, run now, and deleted", async ({ page, context, baseURL }) => {
    await signInAs(context, alice, baseURL!)
    await page.goto("/settings")
    await page.getByLabel("Display name").fill("Alice")
    await page.getByLabel("Tone").selectOption("concise")
    await page.getByLabel("Custom instructions").fill("Always use bullet points.")
    await page.getByRole("button", { name: "Save" }).click()
    await expect(page.getByTestId("prefs-saved")).toBeVisible()
    expect((await backend("/__state")).prefs[alice.id]).toMatchObject({ display_name: "Alice", tone: "concise", instructions: "Always use bullet points." })

    await page.getByLabel("Task title").fill("Morning brief")
    await page.getByLabel("Task question").fill("Summarise my day")
    await page.getByLabel("Google Workspace").check()
    await page.getByRole("button", { name: "Add task" }).click()
    await expect(page.getByTestId("task-1")).toContainText("Morning brief")
    await expect(page.getByTestId("task-1")).toContainText("daily at 08:00 · google")
    await page.getByTestId("task-1").getByRole("button", { name: "Run now" }).click()
    await expect(page.getByTestId("task-1")).toContainText("Ran: Summarise my day")
    await page.getByTestId("task-1").getByRole("button", { name: "Pause" }).click()
    await expect(page.getByTestId("task-1")).toContainText("paused")
    await page.getByTestId("task-1").getByRole("button", { name: "Delete" }).click()
    await expect(page.getByTestId("task-1")).toHaveCount(0)
  })

  test("deep research toggle is sent with the message and remembered", async ({ page, context, baseURL }) => {
    await signInAs(context, alice, baseURL!)
    await page.goto("/chat")
    await page.getByTestId("research-mode").click()
    await expect(page.getByTestId("research-mode")).toHaveAttribute("aria-pressed", "true")
    await ask(page, "state of MoE routing")
    await expectReply(page, "Reply to: state of MoE routing")
    expect((await backend("/__state")).asks.at(-1).mode).toBe("research")
    await page.reload()
    await expect(page.getByTestId("research-mode")).toHaveAttribute("aria-pressed", "true")
  })

  test("Google Workspace: not connected sends you to /vault; connected can be switched on", async ({ page, context, baseURL }) => {
    await signInAs(context, alice, baseURL!)
    await page.goto("/chat")
    await page.getByRole("button", { name: "Add" }).click()
    await page.getByTestId("menu-connectors").click()
    await expect(page.getByTestId("connector-google")).toContainText("Connect your account first")
    await page.getByTestId("connector-google").click()
    await expect(page).toHaveURL(/\/vault/)
    await expect(page.getByTestId("google-workspace")).toContainText("Not connected")
    await expect(page.getByTestId("google-connect")).toContainText("Connect Google Workspace")

    await backend("/__google", { user: alice.id })
    await page.reload()
    await expect(page.getByTestId("google-workspace")).toContainText("Connected · gmail, calendar, drive, docs")
    await page.goto("/chat")
    await page.getByRole("button", { name: "Add" }).click()
    await page.getByTestId("menu-connectors").click()
    await page.getByTestId("connector-google").click()
    await expect(page.getByTestId("connector-google")).toHaveAttribute("aria-checked", "true")
    await page.locator("body").click({ position: { x: 5, y: 5 } })
    await ask(page, "what is on my calendar")
    await expectReply(page, "Reply to: what is on my calendar")
    expect((await backend("/__state")).asks.at(-1).connectors).toEqual(["google"])
  })

  test("a task that pauses for approval can be approved from the settings page", async ({ page, context, baseURL }) => {
    await signInAs(context, alice, baseURL!)
    await page.goto("/settings")
    await page.getByLabel("Task title").fill("Nightly write")
    await page.getByLabel("Task question").fill("APPROVAL save the digest to a file")
    await page.getByRole("button", { name: "Add task" }).click()
    await page.getByTestId("task-1").getByRole("button", { name: "Run now" }).click()
    await expect(page.getByTestId("task-1-approval")).toContainText("needs your approval")
    const approved = page.waitForResponse((r) => r.url().includes("/api/approve"))
    await page.getByTestId("task-1-approval").getByRole("button", { name: "Approve" }).click()
    expect((await approved).status()).toBe(200)
    const state = await backend("/__state")
    expect(state.executed["run-task"]).toBe(1)
  })

  test("deep research chosen on the landing page carries into the chat", async ({ page, context, baseURL }) => {
    await signInAs(context, alice, baseURL!)
    await page.goto("/")
    await page.getByTestId("research-mode").click()
    await ask(page, "history of routing")
    await expect(page).toHaveURL(/\/chat/)
    await expectReply(page, "Reply to: history of routing")
    expect((await backend("/__state")).asks.at(-1).mode).toBe("research")
    await expect(page.getByTestId("research-mode")).toHaveAttribute("aria-pressed", "true")
  })
})
