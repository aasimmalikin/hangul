import { test, expect } from "@playwright/test"
import { alice, ask, backend, expectReply, signInAs } from "./helpers"

/**
 * "+ → Connectors → Research" switches the arXiv connector on for this
 * conversation: it goes up with every message, shows as a chip, survives a
 * reload, and is carried from the landing page into /chat.
 */
test.describe("connectors", () => {
  test.beforeEach(async () => { await backend("/__reset", {}) })

  test("toggle Research in chat, it is sent with the message and shown as a chip", async ({ page, context, baseURL }) => {
    await signInAs(context, alice, baseURL!)
    await page.goto("/chat")
    await page.getByRole("button", { name: "Add" }).click()
    await page.getByTestId("menu-connectors").hover()
    await expect(page.getByTestId("connectors-menu")).toBeVisible()
    await page.getByTestId("connector-arxiv").click()
    await expect(page.getByTestId("connector-arxiv")).toHaveAttribute("aria-checked", "true")
    await page.keyboard.press("Escape")
    await page.locator("body").click({ position: { x: 5, y: 5 } })
    await expect(page.getByTestId("chip-connector-arxiv")).toContainText("Research")

    await ask(page, "papers on mixture of experts")
    await expectReply(page, "Reply to: papers on mixture of experts")
    const state = await backend("/__state")
    expect(state.asks.at(-1).connectors).toEqual(["arxiv"])

    // survives a reload with the thread, and the chip switches it off
    await page.reload()
    await expect(page.getByTestId("chip-connector-arxiv")).toBeVisible()
    await page.getByTestId("chip-connector-arxiv").click()
    await expect(page.getByTestId("chip-connector-arxiv")).toHaveCount(0)
    await ask(page, "and now without")
    await expectReply(page, "Reply to: and now without")
    expect((await backend("/__state")).asks.at(-1).connectors).toEqual([])
  })

  test("a connector chosen on the landing page is on when the chat starts", async ({ page, context, baseURL }) => {
    await signInAs(context, alice, baseURL!)
    await page.goto("/")
    await page.getByRole("button", { name: "Add" }).click()
    await page.getByTestId("menu-connectors").click()          // click works too (touch / keyboard)
    await page.getByTestId("connector-arxiv").click()
    await page.locator("body").click({ position: { x: 5, y: 5 } })
    await expect(page.getByTestId("chip-connector-arxiv")).toBeVisible()

    await page.getByPlaceholder(/Ask/).fill("recent work on routing")
    await page.keyboard.press("Enter")
    await expect(page).toHaveURL(/\/chat/)
    await expectReply(page, "Reply to: recent work on routing")
    expect((await backend("/__state")).asks.at(-1).connectors).toEqual(["arxiv"])
    await expect(page.getByTestId("chip-connector-arxiv")).toBeVisible()
  })

  test("junk connector keys never reach the backend", async ({ page, context, baseURL }) => {
    await signInAs(context, alice, baseURL!)
    const r = await page.request.post("/api/chat", {
      data: { messages: [{ role: "user", parts: [{ type: "text", text: "hi" }] }], connectors: ["arxiv", "../etc", 42, "arxiv"] },
    })
    expect(r.ok()).toBe(true)
    await r.text()
    expect((await backend("/__state")).asks.at(-1).connectors).toEqual(["arxiv"])
  })
})
