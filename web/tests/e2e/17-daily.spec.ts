import { test, expect } from "@playwright/test"
import { ask, backend, expectReply, freshUser, resetBackend, signInAs } from "./helpers"

/** Everyday-assistant tools: checklist and weather cards, the reminder bell, /lists, starter chips. */
test.describe("daily assistant", () => {
  const me = freshUser("daily")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("a list result is a live checklist", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "SHOPPING add milk and eggs")
    await expectReply(page, "Added milk and eggs")
    const card = page.getByTestId("card-todo")
    await expect(card).toContainText("Shopping")
    await card.getByTestId("todo-2").check()
    await expect.poll(async () => (await backend("/__state")).todos[me.id].find((t: { id: number }) => t.id === 2).done).toBe(true)
  })

  test("weather comes back as a card", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "WEATHER in Pune")
    const card = page.getByTestId("card-weather")
    await expect(card).toContainText("Pune")
    await expect(card).toContainText("Light rain")
    await expect(card).toContainText("☔ 80%")
  })

  test("a fired reminder shows in the bell and can be dismissed", async ({ page }) => {
    await backend("/__reminder", { user: me.id, text: "Call mom" })
    await page.goto("/chat")
    await expect(page.getByTestId("reminder-count")).toHaveText("1")
    await page.getByTestId("reminder-bell").click()
    await expect(page.getByTestId("due-1")).toContainText("Call mom")
    await page.getByTestId("due-1").getByRole("button", { name: "Done" }).click()
    await expect(page.getByTestId("reminder-count")).toHaveCount(0)
    // the dismiss is sent in the background: wait for it to land
    await expect.poll(async () => (await backend("/__state")).reminders[me.id][0].status).toBe("done")
  })

  test("/lists adds and shows items", async ({ page }) => {
    await page.goto("/lists")
    await page.getByLabel("New item").fill("Pay rent")
    await page.getByRole("button", { name: "Add" }).click()
    await expect(page.getByTestId("list-To-do")).toContainText("Pay rent")
  })

  test("starter chips fill the composer", async ({ page }) => {
    await page.goto("/chat")
    await page.getByTestId("starters").getByRole("button", { name: "Shopping list" }).click()
    await expect(page.getByRole("textbox").first()).toHaveValue("Add milk, eggs and bread to my shopping list")
  })

  test.describe("in India time", () => {
    test.use({ timezoneId: "Asia/Kolkata" })

    test("the device timezone goes up with each message and on page load", async ({ page }) => {
      await page.goto("/chat")
      // Chromium reports the legacy name; the backend stores it as Asia/Kolkata
      await expect.poll(async () => (await backend("/__state")).deviceTz[me.id]).toMatch(/^Asia\/(Kolkata|Calcutta)$/)
      await ask(page, "what time is it?")
      await expectReply(page, "Reply to: what time is it?")
      const s = await backend("/__state")
      expect(s.asks.at(-1).client_timezone).toMatch(/^Asia\/(Kolkata|Calcutta)$/)
    })
  })
})
