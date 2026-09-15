import { test, expect } from "@playwright/test"
import { freshUser, ask, backendState, expectReply, resetBackend, signInAs } from "./helpers"

const pdf = (name: string, size = 64) => ({ name, mimeType: "application/pdf", buffer: Buffer.alloc(size, 1) })

test.describe("documents", () => {
  const me = freshUser("documents")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("+ → Docs → file → chip; question then goes out", async ({ page }) => {
    await page.goto("/chat")
    await page.getByRole("button", { name: "Add" }).click()
    const [chooser] = await Promise.all([page.waitForEvent("filechooser"), page.getByRole("menuitem", { name: "Docs" }).click()])
    await chooser.setFiles(pdf("handbook.pdf"))
    await expect(page.getByText("handbook.pdf")).toBeVisible()
    await expect(page.getByPlaceholder("Ask about your document…")).toBeVisible()
    expect((await backendState()).uploads[0]).toMatchObject({ user: me.id, filename: "handbook.pdf" })
    await ask(page, "what does it say?")
    await expectReply(page, "what does it say?")
  })

  test("landing page upload carries the document into chat", async ({ page }) => {
    await page.goto("/")
    await page.getByRole("button", { name: "Add" }).click()
    const [chooser] = await Promise.all([page.waitForEvent("filechooser"), page.getByRole("menuitem", { name: "Docs" }).click()])
    await chooser.setFiles(pdf("from-landing.pdf"))
    await expect(page.getByText("from-landing.pdf")).toBeVisible()
    await page.getByPlaceholder(/Ask/).fill("summarise")
    await page.keyboard.press("Enter")
    await expect(page).toHaveURL(/\/chat/)
    await expect(page.getByText("from-landing.pdf")).toBeVisible()
    await expectReply(page, "summarise")
  })

  test("wrong type and oversize files are refused by the BFF, not the backend", async ({ page }) => {
    await page.goto("/chat")
    await page.getByRole("button", { name: "Add" }).click()
    let [chooser] = await Promise.all([page.waitForEvent("filechooser"), page.getByRole("menuitem", { name: "Docs" }).click()])
    await chooser.setFiles({ name: "movie.mp4", mimeType: "video/mp4", buffer: Buffer.alloc(10, 1) })
    await expect(page.getByText("Only PDF, TXT and MD")).toBeVisible()

    await page.getByRole("button", { name: "Add" }).click()
    ;[chooser] = await Promise.all([page.waitForEvent("filechooser"), page.getByRole("menuitem", { name: "Docs" }).click()])
    await chooser.setFiles(pdf("huge.pdf", 11 * 1024 * 1024))
    await expect(page.getByText("larger than 10 MB")).toBeVisible()
    expect((await backendState()).uploads).toHaveLength(0)
  })

  test("upload after the session expired opens the sign-in modal", async ({ page, context }) => {
    await page.goto("/chat")
    await page.waitForLoadState("networkidle") // let the proxy's cookie refresh land first
    await context.clearCookies()
    // Either the client already noticed (session refetch) and gates the +,
    // or it still believes it is signed in and the upload's 401 gates it.
    await page.getByRole("button", { name: "Add" }).click()
    const docs = page.getByRole("menuitem", { name: "Docs" })
    if (await docs.isVisible().catch(() => false)) {
      const [chooser] = await Promise.all([page.waitForEvent("filechooser"), docs.click()])
      await chooser.setFiles(pdf("late.pdf"))
      await expect(page.getByRole("dialog")).toContainText("session has expired")
    } else {
      await expect(page.getByRole("dialog")).toContainText(/Sign in/)
    }
    expect((await backendState()).uploads).toHaveLength(0)
  })
})
