import { test, expect } from "@playwright/test"
import { backend, freshUser, resetBackend, signInAs } from "./helpers"

/** The first-run walkthrough, and the installable app (manifest, icons, service worker, offline page). */
test.describe("first run", () => {
  const me = freshUser("newbie")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await backend("/__onboarding", { user: me.id })
    await signInAs(context, me, baseURL!)
  })

  test("three steps: name and city, Google (skipped), morning brief", async ({ page }) => {
    await page.goto("/")
    const dlg = page.getByTestId("onboarding")
    await expect(dlg.getByTestId("onboarding-1")).toBeVisible()
    await page.getByLabel("Your name").fill("Aasim")
    await dlg.getByLabel("Your city").fill("Pune")
    await dlg.getByRole("button", { name: "Continue" }).click()
    await expect(dlg.getByTestId("onboarding-2")).toContainText("Connect Google?")
    await dlg.getByRole("button", { name: "Not now" }).click()
    await expect(dlg.getByTestId("onboarding-3")).toContainText("A morning brief?")
    await dlg.getByTestId("onboarding-brief").click()
    await expect(dlg).toHaveCount(0)

    const s = await backend("/__state")
    expect(s.prefs[me.id]).toMatchObject({ display_name: "Aasim", city: "Pune", onboarded: true })
    expect(Object.values(s.tasks)[0]).toMatchObject({ title: "Morning brief", daily_at: "08:00", deliver_email: true })
    await expect(page.getByTestId("today")).toContainText("Good morning, Aasim")              // Today picks it up
    await expect(page.getByTestId("today-weather")).toContainText("Pune")
  })

  test("skip is remembered", async ({ page }) => {
    await page.goto("/")
    await page.getByTestId("onboarding-skip").click()
    await expect(page.getByTestId("onboarding")).toHaveCount(0)
    await page.reload()
    await expect(page.getByTestId("today")).toBeVisible()
    await expect(page.getByTestId("onboarding")).toHaveCount(0)
  })
})

test.describe("installable app", () => {
  test("manifest, icons, service worker and offline page", async ({ request }) => {
    const m = await (await request.get("/manifest.webmanifest")).json()
    expect(m).toMatchObject({ short_name: "Hangul", display: "standalone", start_url: "/" })
    for (const icon of m.icons) {
      const r = await request.get(icon.src)
      expect(r.status(), icon.src).toBe(200)
      expect(r.headers()["content-type"]).toContain("image/png")
    }
    const sw = await request.get("/sw.js")
    expect(sw.status()).toBe(200)
    expect(sw.headers()["cache-control"]).toContain("no-cache")
    expect(await sw.text()).toContain("offline.html")
    expect((await request.get("/offline.html")).status()).toBe(200)
    expect((await request.get("/icons/apple-touch-icon.png")).status()).toBe(200)
  })
})
