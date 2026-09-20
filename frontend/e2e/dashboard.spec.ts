import { expect, test } from "@playwright/test";

import { mockShell, seedAuth, seedLang } from "./support";

const dashboardFixture = {
  orders: { orders_count: 4, revenue: 1250, aov: 312.5 },
  ai_orders_30d: 1,
  conversations: { open: 3, unread: 2 },
  customers: 12,
  products_active: 8,
  low_stock: 1,
  daily_orders: [],
  revenue_by_source: [],
};

test.beforeEach(async ({ page }) => {
  await seedAuth(page);
  await seedLang(page, "en");
  // The shell fetches /auth/me, the health badge and the notification bell, and
  // opens the SSE stream. Without these mocked the page under test is competing
  // with three unmocked requests and an SSE retry loop — which is what made this
  // spec fail the first time it ever ran in CI.
  await mockShell(page);
  await page.route("**/api/v1/analytics/dashboard", async (route) => {
    await route.fulfill({ json: dashboardFixture });
  });
});

test("dashboard surfaces actionable attention items", async ({ page }) => {
  await page.goto("/dashboard");

  await expect(page.getByTestId("needs-attention")).toBeVisible();
  await expect(page.getByTestId("attention-unread")).toBeVisible();
  await expect(page.getByTestId("attention-low-stock")).toBeVisible();
  await expect(page.getByTestId("stat-revenue")).toContainText("1250");
});

test("command palette opens and filters navigation", async ({ page }) => {
  await page.goto("/dashboard");

  await page.keyboard.press("Control+k");
  await expect(page.getByTestId("command-input")).toBeVisible();
  // "inventory" rather than the Arabic label: seedLang pins the UI to English so
  // the assertion does not depend on which translation is active.
  await page.getByTestId("command-input").fill("inventory");
  await expect(page.getByTestId("command-nav-inventory")).toBeVisible();
});
