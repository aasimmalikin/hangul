import { test, expect } from "@playwright/test"
import { backend, expectReply, freshUser, resetBackend, signInAs } from "./helpers"

/**
 * Voice: tap-to-talk, read-aloud, hands-free voice mode (incl. a spoken
 * approval) and voice notes. Chromium's fake microphone supplies the audio;
 * the fake backend decides what was "heard" (`POST /__transcripts`).
 */
test.use({
  launchOptions: { args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"] },
  permissions: ["microphone"],
})

test.describe("voice", () => {
  const me = freshUser("voice")
  test.beforeEach(async ({ context, baseURL }) => {
    await resetBackend()
    await signInAs(context, me, baseURL!)
  })

  test("tap to talk sends what was said", async ({ page }) => {
    await page.goto("/chat")
    await page.getByTestId("mic-button").click()
    await expect(page.getByTestId("mic-button")).toHaveAttribute("data-state", "recording")
    await page.waitForTimeout(1200)
    await page.getByTestId("mic-button").click()
    await expectReply(page, "Added milk and eggs")
    const s = await backend("/__state")
    expect(s.transcribed).toHaveLength(1)
    expect(s.transcribed[0].seconds).toBeGreaterThanOrEqual(1)
    expect(s.asks.at(-1).question).toBe("SHOPPING add milk and eggs")
  })

  test("a recording can be discarded instead of sent", async ({ page }) => {
    await page.goto("/chat")
    await page.getByTestId("mic-button").click()
    await expect(page.getByTestId("mic-button")).toHaveAttribute("data-state", "recording")
    await expect(page.getByTestId("mic-button")).toContainText("Stop")
    await page.getByTestId("mic-cancel").click()
    await expect(page.getByTestId("mic-button")).toHaveAttribute("data-state", "idle")
    expect((await backend("/__state")).transcribed).toHaveLength(0)
  })

  test("an answer can be read aloud", async ({ page }) => {
    await page.goto("/chat")
    await page.getByTestId("chat-composer").fill("WEATHER in Pune")
    await page.getByTestId("chat-composer").press("Enter")
    await expectReply(page, "Take an umbrella today.")
    await page.getByTestId("speak-button").last().click()
    await expect.poll(async () => (await backend("/__state")).spoken).toContain("Take an umbrella today.")
  })

  test("voice mode: talk, hear the answer, approve out loud", async ({ page }) => {
    await backend("/__transcripts", { texts: ["APPROVAL write notes", "yes please"] })
    await page.goto("/chat")
    await page.getByTestId("voice-mode-button").click()
    const vm = page.getByTestId("voice-mode")
    await expect(vm).toHaveAttribute("data-phase", "listening")
    await expect(page.getByTestId("speaking-stag")).toHaveAttribute("data-phase", "listening")
    await page.waitForTimeout(800)
    await page.getByTestId("voice-orb").click()                 // done talking
    // the run pauses for approval -> it is asked out loud, then it listens again
    await expect.poll(async () => (await backend("/__state")).spoken.join(" ")).toContain("Should I go ahead? Say yes or no.")
    await expect(vm).toHaveAttribute("data-phase", "listening")
    await page.waitForTimeout(800)
    await page.getByTestId("voice-orb").click()                 // "yes please"
    await expect.poll(async () => (await backend("/__state")).spoken).toContain("Wrote notes.txt.")
    expect(Object.values((await backend("/__state")).executed)).toEqual([1])
    await page.getByTestId("voice-exit").click()
    await expect(vm).toHaveCount(0)
  })

  test("a recorded voice note is uploaded", async ({ page }) => {
    await page.goto("/chat")
    await page.getByRole("button", { name: "Add" }).click()
    await page.getByTestId("menu-voice-note").click()
    await expect(page.getByTestId("voice-note-stop")).toBeVisible()
    await page.waitForTimeout(1500)
    await page.getByTestId("voice-note-stop").click()
    await expect.poll(async () => (await backend("/__state")).uploads.map((u: { filename: string }) => u.filename).join(","))
      .toMatch(/voice-note-\d+\.(webm|ogg|m4a)/)
  })
})
