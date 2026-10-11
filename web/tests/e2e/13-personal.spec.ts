import { test, expect } from "@playwright/test"
import { ask, backend, expectReply, freshUser, openOptions, signInAs } from "./helpers"

/** Personalisation, scheduled tasks, deep research, and the Google Workspace connectors' connect state. */
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
    await page.getByLabel("Gmail").check()
    await page.getByRole("button", { name: "Add task" }).click()
    await expect(page.getByTestId("task-1")).toContainText("Morning brief")
    await expect(page.getByTestId("task-1")).toContainText("daily at 8:00 AM · gmail")
    // the time is picked as hour / minute / AM-PM and stored as 24-hour HH:MM
    await page.getByLabel("Task title").fill("Afternoon check")
    await page.getByLabel("Task question").fill("Anything new?")
    await page.getByLabel("Hour").selectOption("4")
    await page.getByLabel("Minute").selectOption("10")
    await page.getByLabel("AM or PM").selectOption("PM")
    await page.getByRole("button", { name: "Add task" }).click()
    await expect(page.getByTestId("task-2")).toContainText("daily at 4:10 PM")
    expect(Object.values((await backend("/__state")).tasks).find((t) => (t as { title?: string }).title === "Afternoon check")).toMatchObject({ daily_at: "16:10" })
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
    await openOptions(page)
    await page.getByTestId("opt-research").click()
    await expect(page.getByTestId("research-mode")).toHaveAttribute("aria-pressed", "true")
    await ask(page, "state of MoE routing")
    await expectReply(page, "Reply to: state of MoE routing")
    expect((await backend("/__state")).asks.at(-1).mode).toBe("research")
    await page.reload()
    await expect(page.getByTestId("research-mode")).toHaveAttribute("aria-pressed", "true")
  })

  test("Google Workspace: not connected sends you to /vault; each product is switched on on its own", async ({ page, context, baseURL }) => {
    await signInAs(context, alice, baseURL!)
    await page.goto("/chat")
    await page.getByRole("button", { name: "Add" }).click()
    await page.getByTestId("menu-connectors").click()
    await expect(page.getByTestId("connector-group-Google Workspace")).toBeVisible()
    await expect(page.getByTestId("connector-gmail")).toContainText("Connect your account first")
    await page.getByTestId("connector-gmail").click()
    await expect(page).toHaveURL(/\/vault/)
    await expect(page.getByTestId("google-workspace")).toContainText("Not connected")
    await expect(page.getByTestId("google-connect")).toContainText("Connect Google Workspace")

    // Connected, but Drive was not granted: Gmail and Calendar toggle, Drive asks for access.
    await backend("/__google", { user: alice.id, products: ["gmail", "calendar", "docs"] })
    await page.reload()
    await expect(page.getByTestId("google-workspace")).toContainText("Connected · gmail, calendar, docs")
    await page.goto("/chat")
    await page.getByRole("button", { name: "Add" }).click()
    await page.getByTestId("menu-connectors").click()
    await expect(page.getByTestId("connector-drive")).toContainText("Grant Google Drive access")
    await page.getByTestId("connector-gmail").click()
    await expect(page.getByTestId("connector-gmail")).toHaveAttribute("aria-checked", "true")
    await expect(page.getByTestId("connector-calendar")).toHaveAttribute("aria-checked", "false")
    await page.getByTestId("connector-calendar").click()
    await expect(page.getByTestId("connector-calendar")).toHaveAttribute("aria-checked", "true")
    await page.locator("body").click({ position: { x: 5, y: 5 } })
    await expect(page.getByTestId("chip-connector-gmail")).toContainText("Gmail")
    await expect(page.getByTestId("chip-connector-calendar")).toContainText("Google Calendar")
    await ask(page, "what is on my calendar")
    await expectReply(page, "Reply to: what is on my calendar")
    expect((await backend("/__state")).asks.at(-1).connectors).toEqual(["gmail", "calendar"])

    // Switching one off leaves the other on.
    await page.getByTestId("chip-connector-gmail").click()
    await ask(page, "and tomorrow")
    await expectReply(page, "Reply to: and tomorrow")
    expect((await backend("/__state")).asks.at(-1).connectors).toEqual(["calendar"])
  })

  test("a chat saved with the old all-in-one Google connector reopens with each product on", async ({ page, context, baseURL }) => {
    await signInAs(context, alice, baseURL!)
    await page.goto("/")
    await page.evaluate(() => sessionStorage.setItem("hangul:connectors", JSON.stringify(["google", "arxiv"])))
    await page.goto("/chat")
    for (const k of ["gmail", "calendar", "drive", "docs", "arxiv"]) await expect(page.getByTestId(`chip-connector-${k}`)).toBeVisible()
    await expect(page.getByTestId("chip-connector-google")).toHaveCount(0)
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

  test("morning brief is one tap: daily at 08:00, emailed", async ({ page, context, baseURL }) => {
    await backend("/__google", { user: alice.id, products: ["gmail", "calendar"] })
    await signInAs(context, alice, baseURL!)
    await page.goto("/settings")
    await page.getByTestId("brief-offer").getByRole("button", { name: "Set it up" }).click()
    const row = page.getByTestId("task-1")
    await expect(row).toContainText("Morning brief")
    await expect(row).toContainText("daily at 8:00 AM")
    await expect(row).toContainText("emailed")
    await expect(page.getByTestId("brief-offer")).toHaveCount(0)
    const t = (await backend("/__state")).tasks["1"]
    expect(t).toMatchObject({ daily_at: "08:00", deliver_email: true })
    expect(t.connectors).toEqual(expect.arrayContaining(["gmail", "calendar"]))
  })

  test("the morning brief leaves Gmail out when the account can't use it", async ({ page, context, baseURL }) => {
    await backend("/__google", { user: alice.id, products: ["calendar"], restricted: false })
    await signInAs(context, alice, baseURL!)
    await page.goto("/settings")
    await page.getByTestId("brief-offer").getByRole("button", { name: "Set it up" }).click()
    await expect(page.getByTestId("task-1")).toContainText("Morning brief")
    expect((await backend("/__state")).tasks["1"].connectors).toEqual(["calendar"])
  })
})
