import { test, expect } from "@playwright/test"
import { backend, freshUser, resetBackend, signInAs } from "./helpers"

/** Settings → WhatsApp: hidden until the server has WhatsApp; link with one message; unlink. */
test.describe("whatsapp", () => {
  const me = freshUser("whatsapp")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("no WhatsApp section until the server has it set up", async ({ page }) => {
    await page.goto("/settings")
    await expect(page.getByRole("heading", { name: "Scheduled tasks" })).toBeVisible()
    await expect(page.getByTestId("whatsapp-link")).toHaveCount(0)
  })

  test("link with one message, then unlink", async ({ page }) => {
    await backend("/__whatsapp", { user: me.id, enabled: true })
    await page.goto("/settings#whatsapp")
    await page.getByTestId("whatsapp-start").click()
    await expect(page.getByTestId("whatsapp-code")).toContainText("HANGUL 482913")
    await expect(page.getByTestId("whatsapp-open")).toHaveAttribute("href", "https://wa.me/919000000000?text=HANGUL%20482913")
    // the user sends the code from WhatsApp; the page notices on its next check
    await backend("/__whatsapp", { user: me.id, linked: true })
    await expect(page.getByTestId("whatsapp-linked")).toContainText("+91 ••••• 3210", { timeout: 10_000 })
    await page.getByTestId("whatsapp-unlink").click()
    await expect(page.getByTestId("whatsapp-start")).toBeVisible()
  })
})
