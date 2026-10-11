import { test, expect } from "@playwright/test"
import { backend, freshUser, resetBackend, signInAs } from "./helpers"

/** Slow days, handled (harness.missions): a mission waiting for the go-ahead, deciding it on the page,
 *  undo, the trust switch, the Pro gate, and the link from /you. */
test.describe("missions", () => {
  const me = freshUser("missions")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("a slow day waits for one go-ahead, then can be undone", async ({ page }) => {
    await backend("/__missions", { user: me.id, waiting: true })
    await page.goto("/you")
    await page.getByTestId("you-missions").click()
    await expect(page).toHaveURL(/\/missions$/)
    const card = page.getByTestId("mission-700")
    await expect(card).toContainText("Chinar Café: Wednesday looks slow")
    await expect(card).toContainText("Needs you")
    await expect(card).toContainText("A rainy-day offer")
    await expect(card).toContainText("Tried once here")
    await expect(page.getByTestId("mission-month")).toContainText("Slow days spotted")

    await card.getByText("Open").click()
    await expect(page).toHaveURL(/\/missions\/700$/)
    const full = page.getByTestId("mission-700")
    await full.getByTestId("mission-approve").click()
    await expect(full).toContainText("Forward this to your regulars")
    await expect(full).toContainText("Working on it")
    await expect(full).toContainText("You said go ahead.")
    await full.getByTestId("mission-undo").click()
    await expect(full).toContainText("Called off")
    await expect(full).toContainText("You undid this.")
  })

  test("not this time calls it off", async ({ page }) => {
    await backend("/__missions", { user: me.id, waiting: true })
    await page.goto("/missions")
    const card = page.getByTestId("mission-700")
    await card.getByTestId("mission-reject").click()
    await expect(card).toContainText("Called off")
    await expect(card.getByTestId("mission-approve")).toHaveCount(0)
  })

  test("on Free the page says so and a go-ahead is refused", async ({ page }) => {
    await backend("/__missions", { user: me.id, waiting: true, plan: "free" })
    await page.goto("/missions")
    await expect(page.getByTestId("missions-locked")).toContainText("part of Plus")
    await page.getByTestId("mission-700").getByTestId("mission-approve").click()
    await expect(page.getByTestId("mission-700").getByRole("alert")).toContainText("part of Plus")
  })

  test("nothing yet points to How's business", async ({ page }) => {
    await page.goto("/missions")
    await expect(page.getByTestId("missions-empty")).toContainText("How's business")
  })
})
