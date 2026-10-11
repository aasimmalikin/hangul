import { test, expect, type Page } from "@playwright/test"
import { ask, backend, backendState, expectReply, freshUser, resetBackend, signInAs } from "./helpers"

/** Brand Studio: the brand-kit wizard, the studio (photos -> layout -> words -> sizes -> post), captions,
 *  client review links, the kit, plan limits, and the chat's brand chip. */
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64")
const photo = (name: string) => ({ name, mimeType: "image/png", buffer: PNG })

type StudioState = { previews?: Array<Record<string, unknown>> }
const previews = async () => ((await backendState()) as unknown as StudioState).previews ?? []

async function openStudio(page: Page, id = 200) {
  await page.goto(`/brands/${id}`)
  await expect(page.getByTestId("studio-brand")).toHaveText("Chinar Café")
}

test.describe("brands", () => {
  const me = freshUser("brands")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("the brand kit wizard: a name, a vibe, a logo and it's ready", async ({ page }) => {
    await page.goto("/you")
    await page.getByTestId("you-brands").click()
    await expect(page).toHaveURL(/\/brands$/)
    await expect(page.getByTestId("brand-empty")).toContainText("This could be your business")
    await page.getByTestId("brand-add").click()

    await page.getByTestId("brand-name").fill("Chinar Café")
    await page.getByRole("button", { name: "A cosy café in Srinagar" }).click()
    await page.getByTestId("brand-suggest").click()

    await expect(page.getByRole("heading", { name: "Pick a vibe for Chinar Café" })).toBeVisible()
    await expect(page.getByTestId("brand-look")).toHaveCount(3)
    await page.getByTestId("brand-look").nth(2).click()                       // Kashmiri heritage

    await expect(page.getByRole("heading", { name: "Make it yours" })).toBeVisible()
    await page.getByTestId("brand-logo-input").setInputFiles(photo("logo.png"))
    await expect(page.getByTestId("brand-logo-colors")).toContainText("We found these colours in your logo")
    await page.getByRole("button", { name: "Use them" }).click()
    await page.getByTestId("brand-handle").fill("@chinarcafe")
    await page.getByTestId("brand-done").click()

    await expect(page.getByTestId("brand-saved")).toContainText("Chinar Café is ready 🎉")
    await expect(page.getByTestId("brand-first-post")).toHaveAttribute("href", /\/brands\/\d+$/)
    await expect(page.getByTestId("brand-card")).toHaveCount(1)
    await expect(page.getByTestId("brand-slots")).toHaveText("1 of 3 brands used")
  })

  test("the studio: upload a photo, pick a layout, write the words, make every size", async ({ page }) => {
    await backend("/__brands", { user: me.id, brands: [{ name: "Chinar Café" }] })
    await openStudio(page)
    await page.getByTestId("photo-input").setInputFiles([photo("kahwa.png"), photo("shop.png")])
    await expect(page.getByTestId("photo")).toHaveCount(2)
    await expect(page.getByTestId("photo").first()).toHaveAttribute("aria-pressed", "true")

    await page.getByTestId("layout-offer").click()
    await page.getByTestId("word-price").fill("20% OFF")
    await page.getByTestId("word-headline").fill("Weekend special")
    await expect.poll(async () => (await previews()).some((d) => d.layout === "offer" && (d.words as Record<string, string>)?.price === "20% OFF"
                                                         && typeof d.image === "string")).toBe(true)

    await page.getByTestId("size-landscape").click()
    await expect(page.getByTestId("studio-make")).toHaveText(/Make it — 4 sizes/)
    await page.getByTestId("studio-make").click()

    const result = page.getByTestId("post-result")
    await expect(page.getByRole("heading", { name: "Your post is ready ✨" })).toBeVisible()
    await expect(result.getByTestId("result-size")).toHaveCount(4)
    await expect(result.getByTestId("result-zip")).toHaveAttribute("href", /\/api\/posts\/\d+\/zip$/)

    // captions in the brand's voice, editable per platform
    await result.getByTestId("platform-x").click()
    await result.getByTestId("write-captions").click()
    await expect(result.getByTestId("caption-instagram").locator("textarea")).toHaveValue("Fresh kahwa is back ☕ (instagram)")
    await expect(result.getByTestId("caption-x")).toContainText("#chinarcafe")
    await page.getByTestId("result-close").click()

    await page.getByTestId("tab-posts").click()
    await expect(page.getByTestId("post-tile")).toHaveCount(1)
    await expect(page.getByTestId("post-tile")).toContainText("Weekend special")
  })

  test("a client approves through a private link, with no account", async ({ page, browser }) => {
    await backend("/__brands", { user: me.id, brands: [{ name: "Chinar Café" }] })
    await openStudio(page)
    await page.getByTestId("photo-input").setInputFiles(photo("kahwa.png"))
    await page.getByTestId("word-headline").fill("Kahwa ₹80")
    await page.getByTestId("studio-make").click()
    await page.getByTestId("review-link").click()
    const url = await page.getByTestId("review-url").inputValue()
    const token = url.split("/review/")[1]
    await expect(page.getByTestId("review-status")).toContainText("Waiting for your client")

    const client = await browser.newContext()          // no sign-in cookie
    const cp = await client.newPage()
    await cp.goto(`/review/${token}`)
    await expect(cp.getByTestId("review-page")).toContainText("A post for your approval")
    await expect(cp.getByTestId("review-img")).toBeVisible()
    await cp.getByTestId("review-changes").click()
    await expect(cp.getByTestId("review-send-changes")).toBeDisabled()
    await cp.getByTestId("review-comment").fill("Bigger logo please")
    await cp.getByTestId("review-send-changes").click()
    await expect(cp.getByTestId("review-done")).toContainText("your changes were sent")
    await client.close()

    await page.getByTestId("result-close").click()
    await page.getByTestId("tab-posts").click()
    await expect(page).toHaveURL(/tab=posts/)
    await page.reload()
    await expect(page.getByTestId("post-tile")).toContainText("Changes asked")
    await page.getByTestId("post-tile").click()
    await expect(page.getByTestId("review-status")).toContainText("Bigger logo please")
  })

  test("a bad review link says so", async ({ browser }) => {
    const ctx = await browser.newContext()
    const p = await ctx.newPage()
    await p.goto(`/review/review-1.${"y".repeat(43)}`)
    await expect(p.getByTestId("review-gone")).toContainText("This link has ended")
    await ctx.close()
  })

  test("carousels and review links are Pro; Plus is shown the plans", async ({ page }) => {
    await backend("/__brands", { user: me.id, brands: [{ name: "Chinar Café" }] })
    await backend("/__billing", { user: me.id, plan: "plus" })
    await openStudio(page)
    await page.getByTestId("photo-input").setInputFiles([photo("a.png"), photo("b.png")])
    await page.getByTestId("kind-carousel").click()
    await page.getByTestId("photo").nth(1).click()
    await expect(page.getByTestId("slide-headline")).toHaveCount(2)
    await expect(page.getByTestId("size-story")).toBeDisabled()
    await page.getByTestId("studio-make").click()
    await expect(page.getByTestId("studio-refusal")).toContainText("Pro plan")
    await expect(page.getByTestId("studio-refusal").getByRole("link", { name: "See plans" })).toHaveAttribute("href", "/billing?upgrade=pro")
  })

  test("the brand kit: handle and hashtag sets are saved", async ({ page }) => {
    await backend("/__brands", { user: me.id, brands: [{ name: "Chinar Café" }] })
    await page.goto("/brands/200?tab=kit")
    await page.getByTestId("kit-handle").fill("chinarcafe")
    await page.getByTestId("kit-add-tags").click()
    await page.getByTestId("kit-tags").fill("#srinagar #kahwa")
    await page.getByTestId("kit-save").click()
    await expect(page.getByTestId("kit-save")).toHaveText(/Saved/)
  })

  test("the chat's brand chip is sent and the finished post links to the studio", async ({ page }) => {
    await backend("/__brands", { user: me.id, brands: [{ name: "Chinar Café" }, { name: "Zara Boutique" }] })
    await page.goto("/chat")
    await page.getByTestId("brand-chip").click()
    await page.getByTestId("brand-option-201").click()
    await expect(page.getByTestId("brand-chip")).toHaveText(/For: Zara Boutique/)
    await ask(page, "BRANDPOST make a post from kahwa.jpg")
    await expectReply(page, "Here's your post.")
    expect((await backendState()).asks.at(-1)).toMatchObject({ brand_id: 201 })

    const card = page.getByTestId("card-brand-set")
    await expect(card).toContainText("Ready to post · Zara Boutique")
    await expect(card.getByTestId("brand-set-tab")).toHaveCount(2)
    await card.getByTestId("brand-set-tab").nth(1).click()
    await expect(card.getByRole("img")).toHaveAttribute("alt", "Story / WhatsApp status (1080×1920)")

    await ask(page, "BRANDPOST again")
    await expectReply(page, "Here's your post.")
    expect((await backendState()).asks.at(-1)).toMatchObject({ brand_id: null })
    await page.getByTestId("brand-chip").click()
    await page.getByTestId("brand-off").click()
    await ask(page, "BRANDPOST plain")
    await expectReply(page, "Here's your post.")
    expect((await backendState()).asks.at(-1)).toMatchObject({ brand_id: 0 })
  })

  test("a brand named in the message is picked and shown on the chip", async ({ page }) => {
    await backend("/__brands", { user: me.id, brands: [{ name: "Chinar Café" }] })
    await page.goto("/chat")
    await ask(page, "BRANDPOST a poster for Chinar Café")
    await expectReply(page, "Here's your post.")
    await expect(page.getByTestId("brand-chip")).toHaveText(/For: Chinar Café/)
  })

  test("setting up from chat shows the looks in the thread", async ({ page }) => {
    await page.goto("/chat")
    await ask(page, "BRANDSETUP set up my café")
    await expectReply(page, "Pick a look.")
    await expect(page.getByTestId("brand-look")).toHaveCount(3)
    await page.getByTestId("brand-look").first().click()
    await page.getByTestId("brand-done").click()
    await expect(page.getByTestId("brand-saved")).toBeVisible()
    await expect(page.getByTestId("brand-chip")).toHaveText(/For: Chinar Café/)
  })

  test("over the limit offers a slot; Free is pointed at the plans", async ({ page }) => {
    await backend("/__brands", { user: me.id, slots: 1, brands: [{ name: "Chinar Café" }] })
    await page.goto("/brands")
    await expect(page.getByTestId("brand-slots")).toHaveText("1 of 1 brand used")
    await expect(page.getByTestId("brand-full").getByTestId("brand-buy-slot")).toHaveText("Add another brand slot")

    await backend("/__brands", { user: me.id, slots: 0 })
    await page.reload()
    await expect(page.getByTestId("brand-paused")).toBeVisible()
  })

  test("Free with no brands sees the plans", async ({ page }) => {
    await backend("/__brands", { user: me.id, slots: 0 })
    await page.goto("/brands")
    await expect(page.getByTestId("brand-upgrade")).toHaveAttribute("href", "/billing?upgrade=plus")
  })

  test("a brand can be removed, which frees its slot", async ({ page }) => {
    await backend("/__brands", { user: me.id, brands: [{ name: "Chinar Café" }] })
    await page.goto("/brands")
    await page.getByTestId("brand-hide").click()
    await page.getByTestId("brand-hide-confirm").click()
    await expect(page.getByTestId("brand-card")).toHaveCount(0)
    await expect(page.getByTestId("brand-empty")).toBeVisible()
  })
})
