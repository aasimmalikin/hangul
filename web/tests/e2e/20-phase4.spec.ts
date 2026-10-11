import { test, expect } from "@playwright/test"
import { ask, backend, expectReply, freshUser, resetBackend, signInAs } from "./helpers"

/** Phase 4: image, route and GitHub cards (still drawn for old chats); work apps are hidden, a connected one can be disconnected. */
test.describe("phase 4", () => {
  const me = freshUser("phase4")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("a generated image is shown with a download", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "IMAGE draw a robot")
    await expectReply(page, "Done.")
    const img = page.getByTestId("card-image").locator("img")
    await expect.poll(() => img.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth)).toBeGreaterThan(0)
    await expect(page.getByTestId("card-image").getByRole("link", { name: "Download" })).toBeVisible()
  })

  test("a route shows time, distance and directions", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "ROUTE walk to the station")
    const card = page.getByTestId("card-route")
    await expect(card).toContainText("35 min")
    await expect(card).toContainText("2.6 km")
    await expect(card.getByRole("link", { name: "Open directions" })).toHaveAttribute("href", /travelmode=walking/)
  })

  test("GitHub items render as a list", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "GITHUB what's waiting for me")
    await expect(page.getByTestId("card-issues")).toContainText("Fix login")
    await expect(page.getByTestId("card-issues")).toContainText("acme/app#12")
  })

  test("GitHub, Notion and Slack aren't offered; one connected before can be disconnected", async ({ page }) => {
    await page.goto("/chat")
    await page.getByRole("button", { name: "Add" }).click()
    await page.getByTestId("menu-connectors").click()        // click, not hover: the touch path, and steady under load
    await expect(page.getByTestId("connector-gmail")).toBeVisible()
    for (const app of ["github", "notion", "slack"]) await expect(page.getByTestId(`connector-${app}`)).toHaveCount(0)

    await page.goto("/vault")
    await expect(page.getByTestId("work-apps")).toHaveCount(0)

    await backend("/__apps", { user: me.id, apps: { github: true } })
    await page.reload()
    await expect(page.getByTestId("app-github")).toContainText("Connected")
    await expect(page.getByTestId("app-notion")).toHaveCount(0)
    await page.getByTestId("app-github-disconnect").click()
    await expect(page.getByTestId("work-apps")).toHaveCount(0)
    expect((await backend("/__state")).apps[me.id]).toEqual({})
  })
})
