import { test, expect, type Page } from "@playwright/test"
import { backend, freshUser, resetBackend, signInAs } from "./helpers"

/** Every URL the page visits: /chat drops its ?q= as soon as it has sent the question, which can be before a toHaveURL check runs. */
function recordUrls(page: Page) {
  const visited: string[] = []
  page.on("framenavigated", (f) => { if (f === page.mainFrame()) visited.push(decodeURIComponent(f.url().replace(/\+/g, " "))) })
  return visited
}

/** The Hearth homepage (signed out), the living stag on Today, and "What Hangul remembers" on /you. */
test.describe("hearth homepage", () => {
  test("signed out: the homepage, its buttons open sign-up, the stag answers a tap", async ({ page }) => {
    await page.goto("/")
    await expect(page.getByTestId("home-landing")).toBeVisible()
    await expect(page.getByRole("heading", { name: /Your shop.s own assistant/ })).toBeVisible()

    await page.getByTestId("home-start").click()
    await expect(page.getByRole("dialog")).toContainText("Create your account")
    await page.locator(".h-scrim").click({ position: { x: 5, y: 5 } })

    await page.getByTestId("home-plan-plus").click()
    await expect(page.getByRole("dialog")).toContainText("free trial of Plus")
    await page.locator(".h-scrim").click({ position: { x: 5, y: 5 } })

    await page.getByTestId("living-stag-tap").click()
    await expect(page.getByTestId("living-stag-bubble")).toBeVisible()
    await page.getByTestId("living-stag-chip").first().click()
    await expect(page.getByRole("dialog")).toContainText("Create your free account")
  })

  test("the pricing and install sections are there, the footer links the legal pages", async ({ page }) => {
    await page.goto("/")
    await expect(page.getByTestId("home-price-plus")).not.toBeEmpty()
    await expect(page.locator("#install")).toContainText("Add to Home Screen")
    await expect(page.getByTestId("landing-legal").getByRole("link", { name: "Refunds" })).toHaveAttribute("href", "/refunds")
  })
})

for (const [where, timezoneId, plus, pro, other] of [
  ["India", "Asia/Kolkata", "₹499", "₹1,499", "$"],
  ["elsewhere", "Europe/Berlin", "$20", "$100", "₹"],
] as const) {
  test(`signed out in ${where}: the homepage shows only that region's prices`, async ({ browser }) => {
    const ctx = await browser.newContext({ timezoneId })
    const page = await ctx.newPage()
    await page.goto("/")
    await expect(page.getByTestId("home-price-plus")).toContainText(plus)
    await expect(page.getByTestId("home-price-pro")).toContainText(pro)
    await expect(page.locator("#pricing")).not.toContainText(other)
    await ctx.close()
  })
}

test.describe("living stag and memory", () => {
  const me = freshUser("hearth")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("tapping the stag offers the usual request for this hour; a chip asks it", async ({ page }) => {
    await page.goto("/")
    await expect(page.getByTestId("today")).toBeVisible()
    await page.getByTestId("living-stag-tap").click()
    const bubble = page.getByTestId("living-stag-bubble")
    await expect(bubble).toContainText("You usually ask me this")
    await expect(bubble).toContainText("Hangul noticed")
    const visited = recordUrls(page)
    await bubble.getByRole("button", { name: "Brief me" }).click()
    await expect.poll(() => visited.some((u) => /\/chat\?q=.*brief/i.test(u))).toBe(true)
  })

  test("/you lists what Hangul remembers, and Forget removes it", async ({ page }) => {
    await page.goto("/you")
    const mem = page.getByTestId("you-memory")
    await expect(mem).toContainText("Call me Sam")
    await expect(mem.getByTestId("you-memory-item")).toHaveCount(3)
    await mem.getByTestId("you-memory-item").filter({ hasText: "Call me Sam" }).getByTestId("you-memory-forget").click()
    await expect(mem.getByTestId("you-memory-item")).toHaveCount(2)
    await page.reload()
    await expect(page.getByTestId("you-memory")).not.toContainText("Call me Sam")
  })
})

test.describe("Hangul talks first", () => {
  const me = freshUser("talk")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("the morning check-in: a mood gets a reply and the streak, and it is remembered", async ({ page }) => {
    await page.goto("/")
    const talk = page.getByTestId("today-talk")
    await expect(talk).toContainText("How are you feeling today?")
    await page.getByTestId("talk-mood-tired").click()
    await expect(talk).toContainText("I'll keep today light")
    await expect(talk).toContainText("4 mornings in a row together")
    await expect(talk).not.toContainText("How are you feeling today?")
    await page.reload()
    await expect(page.getByTestId("today-talk")).toContainText("I'll keep today light")     // same tab: answered
  })

  test("reopening Hangul asks again, mentioning the earlier answer; a new answer replaces it", async ({ page, context }) => {
    await page.goto("/")
    await page.getByTestId("talk-mood-tired").click()
    await expect(page.getByTestId("today-talk")).toContainText("I'll keep today light")
    const again = await context.newPage()                 // a new tab = Hangul opened again
    await again.goto("/")
    const talk = again.getByTestId("today-talk")
    await expect(talk).toContainText("How are you feeling now? Earlier today you said you were tired.")
    await again.getByTestId("talk-mood-great").click()
    await expect(talk).toContainText("Love that")
    expect((await backend("/__state")).checkins[me.id]).toBe("great")
  })

  test("You told me…: forgetting a memory removes it everywhere", async ({ page }) => {
    await page.goto("/")
    const talk = page.getByTestId("today-talk")
    await expect(talk).toContainText("You told me: “Call me Sam, not Samuel”")
    await page.getByTestId("talk-memory-forget").click()
    await expect(talk).toContainText("Forgotten.")
    await page.goto("/you")
    await expect(page.getByTestId("you-memory-item")).toHaveCount(2)
  })

  test("a reply owed: one tap asks Hangul to draft it in chat", async ({ page }) => {
    await backend("/__today", { user: me.id, extra: { replies: [{ thread_id: "t1", from: "Priya Shah <priya@example.com>", subject: "Thursday's review", waiting_days: 2 }] } })
    await page.goto("/")
    await expect(page.getByTestId("today-talk")).toContainText("Priya Shah has been waiting 2 days")
    const visited = recordUrls(page)
    await page.getByTestId("talk-draft").click()
    await expect.poll(() => visited.some((u) => /\/chat\?q=Draft a reply to Priya Shah/.test(u))).toBe(true)
  })
})

