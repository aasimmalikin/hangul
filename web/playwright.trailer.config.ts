import { defineConfig } from "@playwright/test"
import base from "./playwright.config"

/**
 * The walkthrough video (tests/trailer): the same production build and fake
 * backend as the e2e suite, recorded at 1280x720, with the fake backend in
 * trailer mode (FAKE_TRAILER=1: natural messages pick the canned replies).
 *
 *   npx next build && npx playwright test -c playwright.trailer.config.ts
 *
 * The .webm lands in test-results/; to make an MP4:
 *   ffmpeg -i test-results/walkthrough-Hangul-walkthrough/video.webm -c:v libx264 -crf 20 \
 *          -pix_fmt yuv420p -movflags +faststart -an Hangul-walkthrough.mp4
 */
const servers = Array.isArray(base.webServer) ? base.webServer : base.webServer ? [base.webServer] : []

export default defineConfig({
  ...base,
  testDir: "./tests/trailer",
  timeout: 240_000,
  retries: 0,
  reporter: "list",
  use: {
    ...base.use,
    viewport: { width: 1280, height: 720 },
    deviceScaleFactor: 1,
    timezoneId: "Asia/Kolkata",       // rupee prices, like an owner in India sees them
    locale: "en-IN",
    video: { mode: "on", size: { width: 1280, height: 720 } },
    trace: "off",
  },
  webServer: servers.map((s) => ({ ...s, env: { ...(s.env ?? {}), FAKE_TRAILER: "1" } })),
})
