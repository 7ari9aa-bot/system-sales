import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-warm.ts",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "line" : "list",
  // Locally the server is `next dev`: a cold route under six parallel workers
  // can take longer than the 5s default to finish compiling mid-redirect,
  // which only slows the assertion — it never weakens it.
  expect: { timeout: process.env.CI ? 10_000 : 20_000 },
  use: {
    baseURL: process.env.BASE_URL ?? "http://127.0.0.1:3000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    // CI exercises the artefact that ships: the job builds first and this then
    // serves the production bundle. `next dev` compiles routes on demand, which
    // turns the first hit of each page into a timeout risk under CI load.
    command: process.env.CI ? "npm run start" : "npm run dev",
    url: "http://127.0.0.1:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});