import { test, expect } from "@playwright/test"
import { ask, backend, expectReply, freshUser, resetBackend, signInAs } from "./helpers"

/** Phase 4: image, route and GitHub cards; connecting a work app from /vault turns its connector on in the menu. */
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

  test("connect GitHub at /vault, then switch it on in the chat", async ({ page }) => {
    await page.goto("/chat")
    await page.getByRole("button", { name: "Add" }).click()
    await page.getByTestId("menu-connectors").hover()
    await expect(page.getByTestId("connector-github")).toContainText("Connect your account first")

    await page.goto("/vault")
    await page.getByTestId("app-github-connect").click()
    await page.getByLabel("GitHub token").fill("bad-token-123")
    await page.getByRole("button", { name: "Save" }).click()
    await expect(page.getByTestId("app-github")).toContainText("refused that token")
    await page.getByLabel("GitHub token").fill("github_pat_good123")
    await page.getByRole("button", { name: "Save" }).click()
    await expect(page.getByTestId("app-github")).toContainText("Connected")
    expect((await backend("/__state")).apps[me.id]).toEqual({ github: true })

    await page.goto("/chat")
    await page.getByRole("button", { name: "Add" }).click()
    await page.getByTestId("menu-connectors").hover()
    await page.getByTestId("connector-github").click()
    await expect(page.getByTestId("connector-github")).toHaveAttribute("aria-checked", "true")
  })
})
