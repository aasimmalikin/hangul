// Records the Direction A design walkthrough: node tests/trailer/record-direction-a.mjs <folder with stage.html> <out dir>
import { chromium } from "@playwright/test"
const [dir, out] = process.argv.slice(2)
const scenes = [
  ["A1-Landing.html", "1 · Landing", "Your shop's own assistant.", "One big button: start free on WhatsApp. Plain words, rupee prices, no app store.", [195, 330]],
  ["A2-Onboarding.html", "2 · First run", "Three questions, or just say them.", "Shop name, kind of business and city. Or just say the answers.", [250, 790]],
  ["A3-Today.html", "3 · Today", "One big number first.", "Today's sales against last week and break-even, a warning before a slow day, and today's list in ledger rows.", [195, 330]],
  ["A4-Chat.html", "4 · Chat", "Tell it in one line.", "A quick line or a voice note. The sale comes back as a receipt-style card, so a wrong number is easy to spot.", [335, 790]],
  ["A5-Business.html", "5 · How's business", "Is the shop doing well?", "The week, break-even, best day, and tomorrow's forecast with its reasons: rain, a quiet Sunday.", [195, 560]],
  ["A6-SlowDay.html", "6 · Slow day", "It asks once. You decide.", "The exact post, what each sale still earns, and three clear choices. Nothing goes out on its own.", [195, 770]],
  ["A7-Customers.html", "7 · Customers", "Keep your regulars.", "Birthdays this week, who stopped coming, and a one-tap \"Came in\" at the counter.", [330, 395]],
  ["A8-Post.html", "8 · Make a post", "A post in your colours.", "Pick a photo, type or say the offer, choose where it goes. Ready for Instagram and WhatsApp status.", [130, 790]],
]
const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 }, recordVideo: { dir: out, size: { width: 1280, height: 720 } } })
const page = await ctx.newPage()
await page.goto(`file://${dir}/stage.html`)
await page.waitForTimeout(2600)                              // title card
await page.evaluate(() => card(false))
await page.waitForTimeout(800)
for (const [i, [file, k, t, s, tap]] of scenes.entries()) {
  if (i > 0) await page.evaluate(([f, k, t, s, i]) => scene(i, f, k, t, s), [file, k, t, s, i])
  else await page.evaluate(([k, t, s]) => { document.getElementById("k").textContent = k; document.getElementById("t").textContent = t; document.getElementById("s").textContent = s; document.getElementById("d").children[0].className = "on" }, [k, t, s])
  await page.waitForTimeout(3600)
  await page.evaluate(([x, y]) => tap(x, y), tap)
  await page.waitForTimeout(900)
}
await page.evaluate(() => card(true, "Hangul", "Calm, numbers first · it always asks before it acts"))
await page.waitForTimeout(3000)
await ctx.close()
await browser.close()
