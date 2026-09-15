import { defineConfig, devices } from "@playwright/test"

/**
 * End-to-end suite against the production build, a real NextAuth session
 * cookie, and a fake FastAPI (tests/e2e/fake-backend.mjs) that can be told
 * to fail. Run with `npm run test:e2e` (builds first) or `npm run test:e2e:only`.
 */
const PORT = 3123
const BACKEND_PORT = 8765
const env = {
  ...process.env,
  NODE_ENV: "production",
  PORT: String(PORT),
  AUTH_URL: `http://127.0.0.1:${PORT}`,
  AUTH_TRUST_HOST: "true",
  AUTH_SECRET: "e2e-auth-secret-e2e-auth-secret-e2e",
  FASTAPI_JWT_SECRET: "e2e-service-secret",
  FASTAPI_URL: `http://127.0.0.1:${BACKEND_PORT}`,
  FAKE_BACKEND_PORT: String(BACKEND_PORT),
  AUTH_PG_URL: "postgresql://nobody:nobody@127.0.0.1:1/none",
  AUTH_GOOGLE_ID: "x",
  AUTH_GOOGLE_SECRET: "x",
  AUTH_RESEND_KEY: "x",
  AUTH_EMAIL_FROM: "x@example.com",
}

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
  },
  webServer: [
    {
      command: "node tests/e2e/fake-backend.mjs",
      url: `http://127.0.0.1:${BACKEND_PORT}/healthz`,
      reuseExistingServer: false,
      env,
    },
    {
      command: `npx next start -p ${PORT}`,
      url: `http://127.0.0.1:${PORT}/`,
      reuseExistingServer: false,
      timeout: 120_000,
      env,
    },
  ],
})
