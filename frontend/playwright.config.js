import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.BASE_URL || "http://127.0.0.1:4173";
const runAgainstLocalBuild = !process.env.BASE_URL;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  // Two retries on CI: the live-api suite runs fully parallel against one
  // uvicorn on a small runner, and the API log dump proved the failures are
  // UI-timing races (every request 200, elements slower than the 5s default)
  // — not app breakage. A second attempt absorbs the runner-load spikes.
  retries: process.env.CI ? 2 : 0,
  reporter: "list",
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
    expect: { timeout: 10_000 },
  },
  // The deep crawl registers a real tenant through the UI — it needs the
  // live API (the backend job sets E2E_LIVE_API=1); without a backend the
  // vite proxy errors would fail the whole suite.
  testIgnore: process.env.E2E_LIVE_API ? [] : ["**/deep-crawl.spec.js"],
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: runAgainstLocalBuild
    ? {
        command: "npm run preview -- --host 127.0.0.1",
        url: baseURL,
        reuseExistingServer: !process.env.CI,
        timeout: 30_000,
      }
    : undefined,
});
