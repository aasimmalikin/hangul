import { test, expect } from "@playwright/test"
import { backend, freshUser, signInAs } from "./helpers"

/**
 * Scheduled tasks made easy: the three-step form (what / when / how) with a plain
 * summary, weekday and one-off schedules, apps picked from the words, the one rule
 * (calendar and email just happen; Sheets and Docs changes ask on WhatsApp 5 minutes early)
 * -- and approving a waiting action from a link, signed out.
 */
test.describe("scheduling", () => {
  const me = freshUser("scheduling")
  test.beforeEach(async () => { await backend("/__reset", {}) })

  // the shape the BFF accepts: <payload>.<signature> (the fake backend decides by prefix)
  const LINK = "okWaitingRun1.abcdefghijklmnopqrstuvwxyz012345"

  test("a waiting action can be approved from its link without signing in, once", async ({ page }) => {
    await page.goto(`/approve/${LINK}?d=approve`)
    await expect(page.getByTestId("approve-title")).toHaveText("Add an event to your calendar?")
    await expect(page.getByTestId("approve-link")).toContainText("Focus time")
    await expect(page.getByTestId("approve-link")).toContainText("Nobody — only your calendar")
    await expect(page.getByTestId("approve-link")).toContainText("Tap Approve to confirm")
    // opening the link (what a mail scanner does) decided nothing
    expect((await backend("/__state")).linkDecisions).toEqual({})

    await page.getByTestId("approve-yes").click()
    await expect(page.getByTestId("approve-done")).toContainText("Done ✓")
    await expect(page.getByTestId("approve-done")).toContainText("Added Focus time at 5:15 PM.")
    expect((await backend("/__state")).linkDecisions).toEqual({ [LINK]: "approve" })

    await page.reload()
    await expect(page.getByTestId("approve-closed")).toContainText("Already decided")
  })

  test("reject from the link, and a bad link explains itself", async ({ page }) => {
    await page.goto(`/approve/${LINK}`)
    await page.getByTestId("approve-no").click()
    await expect(page.getByTestId("approve-done")).toContainText("Rejected — nothing was done")

    await page.goto("/approve/badLinkValue.abcdefghijklmnopqrstuvwxyz012345")
    await expect(page.getByTestId("approve-error")).toContainText("expired or isn't valid")
    await page.goto("/approve/not-even-a-link")
    await expect(page.getByTestId("approve-error")).toBeVisible()
  })

  test("weekdays at a set time, apps from the words; calendar just happens", async ({ page, context, baseURL }) => {
    await signInAs(context, me, baseURL!)
    await page.goto("/settings")
    await page.getByLabel("Task question").fill("Find a free slot this afternoon and block an event for focus")
    await expect(page.getByTestId("task-apps")).toContainText("(from your words)")
    await expect(page.getByLabel("Google Calendar")).toBeChecked()
    await expect(page.getByTestId("task-rule")).toContainText("Calendar events and email drafts just happen")
    await page.getByTestId("when-weekdays").click()
    await page.getByLabel("Hour").selectOption("9")
    await page.getByLabel("Minute").selectOption("15")
    await expect(page.getByTestId("task-summary")).toContainText("Every weekday at 9:15 AM, Hangul will:")
    await expect(page.getByTestId("task-summary")).not.toContainText("your OK")
    await page.getByRole("button", { name: "Add task" }).click()

    await expect(page.getByTestId("task-1")).toContainText("weekdays at 9:15 AM")
    const t = (await backend("/__state")).tasks["1"]
    expect(t).toMatchObject({ daily_at: "09:15", days: 31, run_on: null })
    expect(t.connectors).toContain("calendar")
    expect(t.title).toBe("Find a free slot this afternoon and")      // a title was made from the words
  })

  test("sending email asks first: 5 minutes early, on WhatsApp or by email on Free", async ({ page, context, baseURL }) => {
    await signInAs(context, me, baseURL!)
    await page.goto("/settings")
    await page.getByLabel("Task question").fill("Send Priya the weekly report by email")
    await expect(page.getByTestId("task-rule")).toContainText("Sending email needs your OK, so this task starts 5 minutes early")
    await expect(page.getByTestId("task-summary")).toContainText("you'll get an approval 5 minutes before (WhatsApp, or email on Free)")
    await page.getByRole("button", { name: "Add task" }).click()
    await expect(page.getByTestId("task-1")).toContainText("Asks you 5 minutes before — sending email — on WhatsApp")
  })

  test("reading email doesn't ask; a Sheets change does", async ({ page, context, baseURL }) => {
    await signInAs(context, me, baseURL!)
    await page.goto("/settings")
    await page.getByLabel("Task question").fill("Summarise my inbox")
    await expect(page.getByTestId("task-summary")).not.toContainText("your OK")
    await page.getByLabel("Task question").fill("Add today's sales to my spreadsheet")
    await expect(page.getByTestId("task-rule")).toContainText("changes need your OK, so this task starts 5 minutes early")
  })

  test("once, on a date: a past time is refused before it's sent", async ({ page, context, baseURL }) => {
    await signInAs(context, me, baseURL!)
    await page.goto("/settings")
    await page.getByLabel("Task question").fill("Remind me what's due")
    await page.getByTestId("when-once").click()
    const today = new Date()
    const ymd = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
    await page.getByLabel("Date").fill(ymd(today))
    await page.getByLabel("Hour").selectOption("12")
    await page.getByLabel("Minute").selectOption("0")
    await page.getByLabel("AM or PM").selectOption("AM")                   // midnight today: already gone
    await expect(page.getByText("That time has already passed.")).toBeVisible()
    await expect(page.getByRole("button", { name: "Add task" })).toBeDisabled()

    const tomorrow = new Date(today.getTime() + 86_400_000)
    await page.getByLabel("Date").fill(ymd(tomorrow))
    await page.getByRole("button", { name: "Add task" }).click()
    await expect(page.getByTestId("task-1")).toContainText("once on")
    expect((await backend("/__state")).tasks["1"]).toMatchObject({ run_on: ymd(tomorrow), daily_at: "00:00" })
  })
})
