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

  test("a to-do can be ticked off from home", async ({ page }) => {
    await page.goto("/lists")
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
})
