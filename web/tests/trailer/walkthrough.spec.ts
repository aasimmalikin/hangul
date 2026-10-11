import { test, expect, type Page } from "@playwright/test"
import { backend, freshUser, resetBackend, signInAs } from "../e2e/helpers"

/**
 * A ~75-second walkthrough of Hangul for a small-business owner, recorded as a
 * video (playwright.trailer.config.ts). Captions are drawn over the real pages;
 * the data is the fake backend's (Chinar Café), so nothing real is touched.
 */

const RED = "#A8402C"

/** A caption bar over the page (re-added after every navigation by the init script). */
async function caption(page: Page, text: string, hold = 3200) {
  await page.evaluate((t) => (window as unknown as { __cap: (t: string) => void }).__cap(t), text)
  await page.waitForTimeout(hold)
}

async function card(page: Page, title: string, sub: string, hold = 3000) {
  await page.setContent(`<!doctype html><html><body style="margin:0;height:100vh;display:grid;place-items:center;
    background:${RED};color:#fff;font-family:Georgia,'Times New Roman',serif">
    <div style="text-align:center">
      <div style="font-size:84px;letter-spacing:-1px">${title}</div>
      <div style="font:400 26px system-ui,sans-serif;margin-top:14px;opacity:.92">${sub}</div>
    </div></body></html>`)
  await page.waitForTimeout(hold)
}

async function glide(page: Page, pixels: number, steps = 12) {
  for (let i = 0; i < steps; i++) {
    await page.mouse.wheel(0, pixels / steps)
    await page.waitForTimeout(45)
  }
}

async function say(page: Page, text: string) {
  const box = page.getByPlaceholder(/Ask/)
  await box.click()
  await box.pressSequentially(text, { delay: 55 })
  await page.waitForTimeout(350)
  await page.keyboard.press("Enter")
  await expect(page.getByTestId("run-done").last()).toBeAttached({ timeout: 20_000 })
}

test("Hangul walkthrough", async ({ page, context, baseURL }) => {
  const me = { ...freshUser("trailer"), name: "Aasim Malik" }
  await resetBackend()
  await context.addInitScript((red) => {
    ;(window as unknown as { __cap: (t: string) => void }).__cap = (t: string) => {
      let el = document.getElementById("__cap")
      if (!el) {
        el = document.createElement("div")
        el.id = "__cap"
        el.setAttribute("style", `position:fixed;left:50%;bottom:34px;transform:translateX(-50%);z-index:2147483647;
          background:${red};color:#fff;font:600 22px system-ui,sans-serif;padding:12px 22px;border-radius:14px;
          box-shadow:0 8px 30px rgba(0,0,0,.25);max-width:80vw;text-align:center;transition:opacity .3s;pointer-events:none`)
        document.body.appendChild(el)
      }
      el.style.opacity = "0"
      setTimeout(() => { el!.textContent = t; el!.style.opacity = "1" }, 150)
    }
  }, RED)

  // ---------------------------------------------------------------- intro
  await card(page, "Hangul", "Your shop's own assistant", 2800)

  // ---------------------------------------------------------------- the homepage
  await page.goto("/")
  await expect(page.getByTestId("home-landing")).toBeVisible()
  await caption(page, "For shops, cafés, cloud kitchens and salons", 3200)
  await page.locator("#day").scrollIntoViewIfNeeded()
  await caption(page, "It knows your sales, and gets things done", 3400)
  await page.locator("#features").scrollIntoViewIfNeeded()
  await caption(page, "Forecasts, slow-day offers, customers — all on WhatsApp", 3400)
  await page.locator("#pricing").scrollIntoViewIfNeeded()
  await caption(page, "Start free. Upgrade when it pays for itself.", 2800)

  // ---------------------------------------------------------------- signed in: a café with history
  await backend("/__business", { user: me.id, seeded: true, plan: "pro" })
  await backend("/__missions", { user: me.id, waiting: true, plan: "pro" })
  await backend("/__customers", { user: me.id, customers: [
    { id: 801, name: "Riya Sharma", phone: "+919876543210", birthday: "10-12", note: "masala chai, no sugar", visits: 14, last_visit: "2026-10-09" },
    { id: 802, name: "Aman Gupta", phone: "+919800000001", birthday: null, note: "orders on Fridays", visits: 9, last_visit: "2026-10-10" },
    { id: 803, name: "Sana Mir", phone: "+919800000002", birthday: null, note: "", visits: 6, last_visit: "2026-08-20" },
  ] })
  await backend("/__today", { user: me.id, extra: {
    birthdays: [{ name: "Riya Sharma", date: "2026-10-12", in_days: 2, customer: true }],
  } })
  await signInAs(context, me, baseURL!)
  // the owner as Settings would have them: name, city, a business owner
  const r = await page.request.put("/api/settings", { headers: { Origin: baseURL! }, data: {
    display_name: "Aasim", city: "Srinagar", timezone: "Asia/Kolkata", tone: "balanced", language: "", instructions: "", persona: "founder" } })
  expect(r.ok()).toBeTruthy()

  await page.goto("/")
  await expect(page.getByTestId("today")).toBeVisible()
  await page.waitForTimeout(1500)
  await caption(page, "Every morning: your day, before you ask", 3600)
  await glide(page, 420)
  await caption(page, "Reminders, promises, customers' birthdays", 3000)

  // ---------------------------------------------------------------- chat
  await page.goto("/chat")
  await caption(page, "Tell it your sales in one line — Hinglish works", 1200)
  await say(page, "aaj 52 bill, 16,400 ka sale hua")
  await caption(page, "Logged, compared with last week and your break-even", 3600)
  await say(page, "kal kaisa rahega?")
  await caption(page, "It warns you before a slow day — with an offer that keeps your margin", 4200)

  // ---------------------------------------------------------------- how's business
  await page.goto("/business")
  await page.waitForTimeout(1200)
  await caption(page, "How's business: sales, tomorrow's forecast, break-even", 3600)
  await glide(page, 520)
  await caption(page, "Import from Vyapar, Petpooja, PhonePe — or just send a bill photo", 3600)

  // ---------------------------------------------------------------- missions
  await page.goto("/missions")
  await page.waitForTimeout(1000)
  await caption(page, "Slow days, handled: it makes the post and asks you once", 4000)
  await caption(page, "Then checks how the day went — and learns what works", 3400)

  // ---------------------------------------------------------------- customers
  await page.goto("/customers")
  await expect(page.getByTestId("customers-page")).toBeVisible()
  await caption(page, "Your regulars, their birthdays, and who hasn't been in", 3600)

  // ---------------------------------------------------------------- outro
  await card(page, "Hangul", "Start free · It always asks before it acts", 3200)
})
