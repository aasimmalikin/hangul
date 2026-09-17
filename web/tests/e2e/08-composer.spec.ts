import { test, expect, type Page } from "@playwright/test"
import { freshUser, expectReply, resetBackend, signInAs } from "./helpers"

const LONG = "Please write a detailed rollout plan for the billing service migration, covering the canary phase, the metrics we watch, the rollback triggers, who is on call, and how we communicate progress to the rest of the company."

/** Type character-by-character-ish so the box grows with each wrapped line, as a person would see. */
async function typeInto(page: Page, testId: string, text: string) {
  const box = page.getByTestId(testId)
  await box.click()
  await box.pressSequentially(text, { delay: 0 })
  return box
}

test.describe("composer wraps and grows", () => {
  const me = freshUser("composer")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  for (const [path, testId] of [["/", "landing-composer"], ["/chat", "chat-composer"]] as const) {
    test(`${path}: a long question wraps onto new lines instead of scrolling sideways`, async ({ page }) => {
      await page.goto(path)
      const box = page.getByTestId(testId)
      const oneLine = (await box.boundingBox())!.height
      await typeInto(page, testId, LONG)
      const grown = (await box.boundingBox())!.height
      expect(grown).toBeGreaterThan(oneLine * 2)          // several lines, not one
      // nothing to scroll horizontally, and no horizontal scrollbar
      expect(await box.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
      await expect(box).toHaveCSS("overflow-x", "hidden")
      await expect(box).toHaveCSS("white-space", /pre-wrap|break-spaces/)
      // the full text is still there, it just wrapped
      await expect(box).toHaveValue(LONG)
    })
  }

  test("the landing box is wide enough to write in", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 })
    await page.goto("/")
    const w = (await page.getByTestId("landing-composer-box").boundingBox())!.width
    expect(w).toBeGreaterThanOrEqual(600)
    expect(w).toBeLessThanOrEqual(640)
  })

  test("Shift+Enter adds a line, Enter sends — on both pages", async ({ page }) => {
    await page.goto("/")
    const landing = page.getByTestId("landing-composer")
    await landing.click()
    await landing.pressSequentially("first line", { delay: 0 })
    await page.keyboard.press("Shift+Enter")
    await landing.pressSequentially("second line", { delay: 0 })
    await expect(landing).toHaveValue("first line\nsecond line")
    const h1 = (await landing.boundingBox())!.height
    for (let i = 0; i < 12; i++) { await page.keyboard.press("Shift+Enter"); await landing.pressSequentially(`more ${i}`, { delay: 0 }) }
    const h2 = (await landing.boundingBox())!.height
    expect(h2).toBeGreaterThan(h1)
    expect(h2).toBeLessThanOrEqual(200 + 1)               // capped, then it scrolls
    await expect(landing).toHaveCSS("overflow-y", "auto")

    await page.keyboard.press("Enter")                     // sends → /chat
    await expect(page).toHaveURL(/\/chat/)
    await expectReply(page, "Reply to: first line")

    const chat = page.getByTestId("chat-composer")
    await chat.click()
    await chat.pressSequentially("a", { delay: 0 })
    await page.keyboard.press("Shift+Enter")
    await chat.pressSequentially("b", { delay: 0 })
    await expect(chat).toHaveValue("a\nb")
    await page.keyboard.press("Enter")
    await expectReply(page, "Reply to: a")
  })
})
