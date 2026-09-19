import { expect, test } from "@playwright/test";

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
  await page.addInitScript(() => {
    window.localStorage.setItem(
      "sales_os_tokens",
      JSON.stringify({ access_token: "test-access", refresh_token: "test-refresh" }),
    );
  });
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
  await page.getByTestId("command-input").fill("مخزون");
  await expect(page.getByTestId("command-nav-inventory")).toBeVisible();
});