import { test, expect } from "@playwright/test"
import { alice, backend, operator, signInAs } from "./helpers"

/**
 * /admin is operator-only. The BFF (`requireAdmin`) demands a recent Google
 * session; the backend applies its email allowlist and audits every call.
 */
test.describe("admin console", () => {
  test.beforeEach(async () => { await backend("/__reset", {}) })

  test("the settings gear on the landing page leads to the console", async ({ page }) => {
    await page.goto("/")
    await page.getByRole("button", { name: "Settings" }).click()
    await page.getByTestId("settings-admin").click()
    await expect(page).toHaveURL(/\/admin$/)
  })

  test("signed out: a Google-only gate, nothing reaches the backend", async ({ page }) => {
    await page.goto("/admin")
    await expect(page.getByTestId("admin-gate")).toContainText("Operator sign-in")
    await expect(page.getByTestId("admin-google")).toContainText("Continue with Google")
    expect((await backend("/__state")).adminCalls).toHaveLength(0)
    // and the API answers 401 with a stable code, uncached and unindexed
    const r = await page.request.get("/api/admin/whoami")
    expect(r.status()).toBe(401)
    expect((await r.json()).code).toBe("unauthorized")
    expect(r.headers()["cache-control"]).toContain("no-store")
    expect(r.headers()["x-robots-tag"]).toContain("noindex")
  })

  test("a magic-link session is sent back to Google, before the backend is asked", async ({ page, context, baseURL }) => {
    await signInAs(context, operator, baseURL!, { provider: "resend" })
    await page.goto("/admin")
    await expect(page.getByTestId("admin-gate")).toContainText("Sign in again with Google")
    expect((await backend("/__state")).adminCalls).toHaveLength(0)
    const r = await page.request.get("/api/admin/whoami")
    expect((await r.json()).code).toBe("reauth_required")
  })

  test("a stale Google session must re-authenticate", async ({ page, context, baseURL }) => {
    await signInAs(context, operator, baseURL!, { authAt: Date.now() - 13 * 3600 * 1000 })
    await page.goto("/admin")
    await expect(page.getByTestId("admin-gate")).toContainText("too old")
    expect((await backend("/__state")).adminCalls).toHaveLength(0)
  })

  test("a Google account that is not on the backend allowlist is refused by the backend", async ({ page, context, baseURL }) => {
    await signInAs(context, alice, baseURL!)
    await page.goto("/admin")
    await expect(page.getByTestId("admin-gate")).toContainText("Not an administrator")
    await expect(page.getByTestId("admin-gate")).toContainText(alice.email)
    const r = await page.request.get("/api/admin/evals?view=catalog")
    expect(r.status()).toBe(403)
    expect((await r.json()).code).toBe("forbidden")
    // the decision was the backend's: it saw the request and said no
    expect((await backend("/__state")).adminCalls).toHaveLength(0)
  })

  test("the operator sees the console, opens a report and starts a run; every call is attributed", async ({ page, context, baseURL }) => {
    await signInAs(context, operator, baseURL!)
    await page.goto("/admin")

    await expect(page.getByTestId("admin-identity")).toContainText(operator.email)
    await expect(page.getByTestId("suite-qa")).toContainText("gate: passing")
    await expect(page.getByTestId("suite-tool_selection")).toContainText("tool_choice")
    await expect(page.getByTestId("eval-tool_choice")).toContainText("Right tools called")
    await page.getByText("Planned (1)").click()
    await expect(page.getByText("needs: scripted conversations")).toBeVisible()

    await page.getByRole("button", { name: /20260918-100000/ }).click()
    await expect(page.getByRole("table")).toContainText("search_docs → web_search")
    await expect(page.getByRole("table")).toContainText("unexpected ['web_search']")

    page.once("dialog", (d) => d.accept())
    await page.getByTestId("run-tool_selection").click()
    await expect(page.getByTestId("run-tool_selection")).toContainText("running tool_selection")

    const state = await backend("/__state")
    expect(state.evalRuns.tool_selection.started_by).toBe(operator.id)
    expect(state.adminCalls.length).toBeGreaterThan(0)
    expect(state.adminCalls.every((c: { user: string; email: string }) => c.user === operator.id && c.email === operator.email)).toBe(true)
  })

  test("a run cannot be started cross-site", async ({ page, context, baseURL }) => {
    await signInAs(context, operator, baseURL!)
    const r = await page.request.post("/api/admin/evals/run", {
      headers: { Origin: "https://evil.example", "Content-Type": "application/json" },
      data: { suite: "qa" },
    })
    expect(r.status()).toBe(403)
    expect((await r.json()).code).toBe("forbidden_origin")
    expect((await backend("/__state")).evalRuns).toEqual({})
  })
})
