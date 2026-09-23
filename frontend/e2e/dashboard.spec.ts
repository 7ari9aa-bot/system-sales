import { expect, test, type Page } from "@playwright/test";

import { json, mockShell, seedAuth, seedLang } from "./support";

/** The `/analytics/dashboard` payload, shaped by the wave-4 read models
 *  (`marketing.analytics.dashboard_summary` + `orders_summary` +
 *  `daily_orders`). It carries NO `orders.revenue`, NO `orders.aov` and NO
 *  `low_stock`: money arrives as named gross/refunded/net/excess families and
 *  stock health as two bands. `tenants/{id}/currency` is mocked with a
 *  DIFFERENT code so an "EGP" on screen can only have come from the summary
 *  itself (§47). */
const dashboardFixture = {
  orders: {
    orders_count: 4,
    gross_revenue: 1250,
    refunded_amount: 200,
    net_revenue: 1050,
    refund_excess: 0,
    gross_aov: 312.5,
    net_aov: 262.5,
    currency: "EGP",
    timezone: "Africa/Cairo",
  },
  ai_orders_30d: 1,
  conversations: { open: 3, unread: 2 },
  customers: 12,
  products_active: 8,
  low_stock_count: 1,
  out_of_stock_count: 2,
  low_stock_threshold: 2,
  daily_orders: [
    {
      day: "2026-09-18",
      orders: 3,
      gross_revenue: 900,
      refunded_amount: 0,
      net_revenue: 900,
      refund_excess: 0,
    },
    {
      day: "2026-09-19",
      orders: 1,
      gross_revenue: 350,
      refunded_amount: 200,
      net_revenue: 150,
      refund_excess: 0,
    },
  ],
  revenue_by_source: [
    { source: "facebook", revenue: 800, conversions: 3 },
    { source: "direct", revenue: 450, conversions: 2 },
  ],
};

/** Install the shell + dashboard + tenant-currency mocks for a page. */
async function mockDashboard(page: Page, body: unknown = dashboardFixture) {
  await mockShell(page);
  await page.route("**/api/v1/tenants/*/currency", (route) =>
    json(route, { tenant_id: "tenant-1", currency: "USD" }),
  );
  await page.route("**/api/v1/analytics/dashboard", (route) => json(route, body));
}

test.beforeEach(async ({ page }) => {
  await seedAuth(page);
  await seedLang(page, "en");
  // The shell fetches /auth/me, the health badge and the notification bell, and
  // opens the SSE stream. Without these mocked the page under test is competing
  // with three unmocked requests and an SSE retry loop — which is what made this
  // spec fail the first time it ever ran in CI.
  await mockDashboard(page);
});

test("dashboard surfaces actionable attention items", async ({ page }) => {
  await page.goto("/dashboard");

  await expect(page.getByTestId("needs-attention")).toBeVisible();
  await expect(page.getByTestId("attention-unread")).toBeVisible();
  // Two stock bands, from two keys: `low_stock_count` and `out_of_stock_count`.
  await expect(page.getByTestId("attention-low-stock")).toContainText("1 product");
  await expect(page.getByTestId("attention-sold-out")).toContainText("2 item");
});

test("money cards show the gross and net families, not one 'revenue'", async ({ page }) => {
  await page.goto("/dashboard");

  await expect(page.getByTestId("stat-gross-revenue")).toContainText("1,250.00 EGP");
  await expect(page.getByTestId("stat-net-revenue")).toContainText("1,050.00 EGP");
  // The gap between the two families stays on screen: the refunded figure.
  await expect(page.getByTestId("stat-net-revenue")).toContainText("Refunded: 200.00 EGP");
  // AOV is named for its family too, with the other one as the hint.
  await expect(page.getByTestId("stat-aov")).toContainText("262.50 EGP");
  await expect(page.getByTestId("stat-aov")).toContainText("312.50 EGP");
});

test("currency comes from the money payload, not the tenant read or a literal", async ({ page }) => {
  // /tenants/tenant-1/currency is mocked as USD; the summary says EGP and the
  // summary is the source the read model shipped with the figures.
  await page.goto("/dashboard");

  await expect(page.getByTestId("stat-gross-revenue")).toContainText("EGP");
  await expect(page.getByTestId("stat-gross-revenue")).not.toContainText("USD");
});

test("a floored net reports the refund excess instead of hiding it", async ({ page }) => {
  // A window that refunded more than it collected: net_revenue is 0 upstream
  // and the 300 that could not be subtracted ships as refund_excess.
  await page.route("**/api/v1/analytics/dashboard", (route) =>
    json(route, {
      ...dashboardFixture,
      orders: {
        ...dashboardFixture.orders,
        gross_revenue: 500,
        refunded_amount: 800,
        net_revenue: 0,
        refund_excess: 300,
        gross_aov: 125,
        net_aov: 0,
      },
    }),
  );

  await page.goto("/dashboard");

  await expect(page.getByTestId("stat-net-revenue")).toContainText("0.00 EGP");
  await expect(page.getByTestId("refund-excess-note")).toBeVisible();
  await expect(page.getByTestId("refund-excess-note")).toContainText("300.00 EGP");
});

test("the daily chart is net money per merchant day", async ({ page }) => {
  await page.goto("/dashboard");

  await expect(page.getByTestId("daily-net-chart")).toBeVisible();
  await expect(page.getByTestId("daily-bar-2026-09-18")).toBeVisible();
  await expect(page.getByTestId("daily-bar-2026-09-19")).toBeVisible();
});

test("source rows are labelled attributed credit, not collected revenue", async ({ page }) => {
  await page.goto("/dashboard");

  const card = page.getByTestId("attributed-by-source");
  await expect(card).toContainText("Attributed revenue by source");
  await expect(card).toContainText("not necessarily money collected");
  await expect(card).toContainText("800.00 EGP");
});

test("no card renders undefined or NaN from a removed key", async ({ page }) => {
  await page.goto("/dashboard");

  // Every money/stock key this screen reads exists on the payload: a stale
  // `orders.revenue` / `orders.aov` / `low_stock` read comes out as
  // "undefined" or "NaN" in the DOM, which is what this catches.
  await expect(page.locator("body")).not.toContainText(/undefined|NaN/);
});

test("command palette opens and filters navigation", async ({ page }) => {
  // The Ctrl+K listener is attached by hydrated React — a press before that is
  // silently lost. /auth/me is fetched by client-side React Query, so waiting
  // for its response proves the app is live before the shortcut is sent.
  const hydrated = page.waitForResponse("**/api/v1/auth/me");
  await page.goto("/dashboard");
  await hydrated;

  await page.keyboard.press("Control+k");
  await expect(page.getByTestId("command-input")).toBeVisible();
  // "inventory" rather than the Arabic label: seedLang pins the UI to English so
  // the assertion does not depend on which translation is active.
  await page.getByTestId("command-input").fill("inventory");
  await expect(page.getByTestId("command-nav-inventory")).toBeVisible();
});
