import { test, expect } from "@playwright/test"
import { ask, backend, expectReply, freshUser, openOptions, resetBackend, signInAs } from "./helpers"

/** The Today home screen, the simplified composer (Options), and connected apps on by default. */
test.describe("today", () => {
  const me = freshUser("today")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("home shows the day: greeting, tasks, approvals, and asks for a city for weather", async ({ page }) => {
    await backend("/__reminder", { user: me.id, text: "Call mom" })
    await page.goto("/")
    await expect(page.getByTestId("today")).toContainText("Good morning")
    await expect(page.getByTestId("today-tasks")).toContainText("Call mom")
    await expect(page.getByTestId("today-events")).toContainText("Connect Google Calendar")
    // no city yet: one field, then the weather appears
    await page.getByLabel("Your city").fill("Pune")
    await page.getByTestId("today-city").getByRole("button", { name: "Save" }).click()
    await expect(page.getByTestId("today-weather")).toContainText("27° light rain in Pune")
    await expect(page.getByTestId("today-weather")).toContainText("take an umbrella")
  })

  test("'Needs you' appears only when something needs the user", async ({ page }) => {
    await page.goto("/")
    await expect(page.getByTestId("today-tasks")).toBeVisible()
    await expect(page.getByTestId("today-needs")).toHaveCount(0)          // nothing waiting: no tile at all
    // an approval waiting in a chat
    await page.goto("/chat")
    await ask(page, "APPROVAL write the notes")
    await expect(page.getByTestId("approval-card").or(page.getByRole("button", { name: /approve/i })).first()).toBeVisible()
    await page.goto("/")
    await expect(page.getByTestId("today-needs")).toBeVisible()
    await expect(page.getByTestId("today-approval")).toContainText("waiting for your OK")
  })

  test("important unread mail shows under 'Needs you'", async ({ page }) => {
    await backend("/__google", { user: me.id })
    await page.goto("/")
    await expect(page.getByTestId("today-needs")).toContainText("Statement ready")
    await expect(page.getByTestId("today-inbox")).toBeVisible()
  })

  test("leave by: asks for a home address, then says when to go", async ({ page }) => {
    const soon = new Date(Date.now() + 2 * 3600_000).toISOString()
    await backend("/__today", { user: me.id, extra: { leave_by: { summary: "Dentist", start: soon, location: "FC Road, Pune", needs_home: true } } })
    await page.goto("/")
    await expect(page.getByTestId("today-leave")).toContainText("Dentist")
    await expect(page.getByTestId("today-leave-home")).toHaveAttribute("href", "/settings#home")
    await backend("/__today", { user: me.id, extra: { leave_by: { summary: "Dentist", start: soon, location: "FC Road, Pune",
      minutes: 25, leave_at: new Date(Date.now() + 85 * 60_000).toISOString(), late: false, link: "https://www.google.com/maps/dir/" } } })
    await page.reload()
    await expect(page.getByTestId("today-leave")).toContainText("Leave by")
    await expect(page.getByTestId("today-leave")).toContainText("25 min drive")
    await expect(page.getByRole("link", { name: "Directions →" })).toBeVisible()
  })

  test("birthdays this week, with a one-tap wish", async ({ page }) => {
    await backend("/__today", { user: me.id, extra: { birthdays: [{ name: "Priya", date: "2026-10-05", in_days: 0, turns: 31 }] } })
    await page.goto("/")
    await expect(page.getByTestId("today-birthdays")).toContainText("Priya")
    await expect(page.getByTestId("today-birthdays")).toContainText("Today · turns 31")
    await page.getByTestId("today-birthday-wish").click()
    await expect(page).toHaveURL(/\/chat/)          // the wish is drafted in a chat
  })

  test("tomorrow shows in the evening, and is hidden when empty", async ({ page }) => {
    await backend("/__today", { user: me.id, extra: { tomorrow: { date_label: "Sunday, 04 October",
      events: [{ summary: "Flight to Delhi", start: "2026-10-04T07:10:00+05:30", end: "2026-10-04T09:30:00+05:30" }],
      reminders: [{ id: 9, text: "Pack bag", due_at: "2026-10-04T06:00:00+05:30" }] } } })
    await page.goto("/")
    const t = page.getByTestId("today-tomorrow")
    await expect(t).toContainText("Tomorrow · Sunday, 04 October")
    await expect(t).toContainText("Flight to Delhi")
    await expect(t).toContainText("Pack bag")
    await backend("/__today", { user: me.id, extra: { tomorrow: { date_label: "Sunday, 04 October", events: [], reminders: [] } } })
    await page.reload()
    await expect(page.getByTestId("today-tasks")).toBeVisible()
    await expect(page.getByTestId("today-tomorrow")).toHaveCount(0)
  })

  test("replies you owe, with a one-tap draft", async ({ page }) => {
    await backend("/__today", { user: me.id, extra: { replies: [
      { thread_id: "18c2f", from: "Priya Shah <priya@acme.com>", subject: "Contract changes", waiting_days: 3 },
      { thread_id: "18c30", from: "Ravi <ravi@x.com>", subject: "Dinner Saturday?", waiting_days: 1 }] } })
    await page.goto("/")
    const card = page.getByTestId("today-replies")
    await expect(card).toContainText("Replies you owe · 2")
    await expect(card.getByTestId("today-reply").first()).toContainText("Priya Shah")
    await expect(card.getByTestId("today-reply").first()).toContainText("3 days")
    await expect(card.getByTestId("today-reply").first()).toHaveAttribute("href", "https://mail.google.com/mail/u/0/#inbox/18c2f")
    await page.getByTestId("today-draft-replies").click()
    await expect(page).toHaveURL(/\/chat/)
  })

  test("no replies card when nobody is waiting", async ({ page }) => {
    await backend("/__today", { user: me.id, extra: { replies: [] } })
    await page.goto("/")
    await expect(page.getByTestId("today-tasks")).toBeVisible()
    await expect(page.getByTestId("today-replies")).toHaveCount(0)
  })

  test("a to-do can be ticked off from home", async ({ page }) => {
    await page.goto("/kept#holding")
    await page.getByLabel("New item").fill("Buy milk")
    await page.getByRole("button", { name: "Add" }).click()
    await page.goto("/")
    await page.getByTestId("today-todo-1").click()        // ticked items leave the list right away
    await expect.poll(async () => (await backend("/__state")).todos[me.id][0].done).toBe(true)
  })

  test("home prompts: one sends, one fills the box", async ({ page }) => {
    await page.goto("/")
    await page.getByRole("button", { name: "Remind me…" }).click()
    await expect(page.getByTestId("landing-composer")).toHaveValue("Remind me to ")
    await page.getByRole("button", { name: "Plan my day" }).click()
    await expect(page).toHaveURL(/\/chat/)
    await expectReply(page, "Reply to: Plan my day")
  })

  test("composer: options are tucked away and connected apps are on by default", async ({ page }) => {
    await page.goto("/chat")
    await expect(page.getByTestId("model-picker")).toHaveCount(0)          // not in the way
    await expect(page.getByTestId("docs-only")).toHaveCount(0)
    await ask(page, "summarise my unread emails")
    await expectReply(page, "Reply to: summarise my unread emails")
    expect((await backend("/__state")).asks.at(-1).connectors_auto).toBe(true)

    await openOptions(page)
    await page.getByTestId("opt-auto-apps").click()                        // switch it off
    await ask(page, "and now without")
    await expectReply(page, "Reply to: and now without")
    expect((await backend("/__state")).asks.at(-1).connectors_auto).toBe(false)
  })

  test("the greeting and to-dos show before the slow parts arrive", async ({ page }) => {
    await backend("/__reminder", { user: me.id, text: "Call mom" })
    await backend("/__today", { user: me.id, slowMs: 2500 })
    await page.goto("/")
    // the quick brief: greeting, reminders and the dots where Hangul's messages go; calendar still being checked
    await expect(page.getByTestId("today")).toContainText("Good morning", { timeout: 2000 })
    await expect(page.getByTestId("today-tasks")).toContainText("Call mom")
    await expect(page.getByTestId("today-events")).toContainText("Checking your calendar")
    await expect(page.getByTestId("today-talk-loading")).toBeVisible()
    await expect(page.getByTestId("today-loading")).toHaveCount(0)
    // then the full brief replaces it
    await expect(page.getByTestId("today-talk-loading")).toHaveCount(0, { timeout: 6000 })
    await expect(page.getByTestId("today-talk")).toBeVisible()
    await expect(page.getByTestId("today-events")).toContainText("Connect Google Calendar")
  })
})
