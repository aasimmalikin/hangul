import { test, expect } from "@playwright/test"
import { ask, expectReply, freshUser, resetBackend, signInAs } from "./helpers"

/** Google Meet: a Join button on events with a Meet link, instant links, recent calls and transcripts. */
test.describe("google meet", () => {
  const me = freshUser("meet")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("an event with a Meet link has a Join button", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "MEET event call with Priya tomorrow at 10")
    await expectReply(page, "Done.")
    const agenda = page.getByTestId("calendar-agenda")
    await expect(agenda).toContainText("Call with Priya")
    await expect(agenda.getByTestId("meet-join")).toHaveAttribute("href", "https://meet.google.com/abc-defg-hij")
  })

  test("an instant meeting shows its link to join or copy", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "MEET link give me a meet link")
    const card = page.getByTestId("meet-link")
    await expect(card).toContainText("meet.google.com/abc-defg-hij")
    await expect(card.getByTestId("meet-join")).toBeVisible()
    await expect(card.getByTestId("meet-copy")).toBeVisible()
  })

  test("recent calls list who joined and how long", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "MEET calls who was on my calls")
    const card = page.getByTestId("meet-meetings")
    await expect(card).toContainText("Guest, Rahul")
    await expect(card).toContainText("42 min · transcript")
  })

  test("a transcript shows speakers and expands", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "MEET transcript summarise the last call")
    const card = page.getByTestId("meet-transcript")
    await expect(card).toContainText("Rahul: I'll send the quote by Friday.")
    await expect(card).not.toContainText("Line 9")
    await card.getByTestId("meet-transcript-toggle").click()
    await expect(card).toContainText("Line 9")
    await expect(card.getByRole("link", { name: "Open in Docs" })).toHaveAttribute("href", /docs\.google\.com/)
  })
})
