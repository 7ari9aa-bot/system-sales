import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.BASE_URL || "http://127.0.0.1:4173";
const runAgainstLocalBuild = !process.env.BASE_URL;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
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
