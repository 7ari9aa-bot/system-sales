import { expect, test, type Page } from "@playwright/test";

import { json, mockShell, seedAuth, seedLang } from "./support";

/* Wave-4 money discipline on the marketing screen (ADR-053, §167, gap M11).
 *
 * `/analytics/summary` now returns `orders_summary` as the named gross /
 * refunded / net / excess family, and each `campaign_budget_roas` row carries
 * `budget_roas`, `spend_roas` and the `basis` that produced the shown ratio.
 * There is no burned-spend feed in this schema, so `actual_spend` and
 * `spend_roas` are `null` — the honest render is a stated "no spend feed", and
 * a `null` must never reach the screen as 0 or NaN. */

const summaryFixture = {
  orders_summary: {
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
  revenue_by_source: [{ source: "facebook", revenue: 800, conversions: 3 }],
  revenue_by_campaign: [
    { campaign_id: "c1", campaign_name: "Ramadan", revenue: 800, conversions: 3 },
  ],
  campaign_budget_roas: [
    {
      campaign_id: "c1",
      name: "Ramadan",
      revenue: 800,
      planned_budget: 400,
      actual_spend: null,
      basis: "planned_budget",
      budget_roas: 2,
      spend_roas: null,
    },
    {
      campaign_id: "c2",
      name: "Zero-budget test",
      revenue: 100,
      planned_budget: null,
      actual_spend: null,
      basis: "planned_budget",
      budget_roas: null,
      spend_roas: null,
    },
  ],
};

const campaignsFixture = {
  items: [
    { id: "c1", name: "Ramadan", provider: "facebook", status: "active", budget: "400.00" },
    { id: "c2", name: "Zero-budget test", provider: "google", status: "draft", budget: null },
  ],
};

async function mockMarketing(page: Page) {
  await mockShell(page);
  await page.route("**/api/v1/tenants/*/currency", (route) =>
    json(route, { tenant_id: "tenant-1", currency: "USD" }),
  );
  await page.route("**/api/v1/marketing/campaigns**", (route) => json(route, campaignsFixture));
  await page.route("**/api/v1/analytics/summary**", (route) => json(route, summaryFixture));
}

test.beforeEach(async ({ page }) => {
  await seedAuth(page);
  await seedLang(page, "en");
  await mockMarketing(page);
});

test("collected money is shown as gross, net and refunded — never one 'revenue'", async ({
  page,
}) => {
  await page.goto("/marketing");

  // The code is the one `orders_summary` carried (USD from the tenant read is
  // the fallback only), per §47.
  await expect(page.getByTestId("mk-gross-revenue")).toContainText("1,250.00 EGP");
  await expect(page.getByTestId("mk-net-revenue")).toContainText("1,050.00 EGP");
  await expect(page.getByTestId("mk-refunded")).toContainText("200.00 EGP");
});

test("campaign return names its basis and states the missing spend feed", async ({ page }) => {
  await page.goto("/marketing");

  const card = page.getByTestId("campaign-return");
  // The ratio the backend produced (revenue 800 / planned budget 400) is shown
  // with the denominator that made it, not under a bare "ROAS" claim.
  await expect(card).toContainText("2.00×");
  await expect(card).toContainText("Return on planned budget");
  // Attribution column is honest about being credited value, not collections.
  await expect(card).toContainText("Attributed revenue");
  await expect(card.getByTestId("attributed-credit").first()).toContainText("800.00 EGP");
  // Every row's spend cell is the explicit no-feed state: no spend feed exists,
  // so a 0 there would be a fabricated number.
  await expect(card.getByTestId("no-spend-feed")).toHaveCount(2);
});

test("a ratio with no denominator renders as a stated state, not 0 or NaN", async ({ page }) => {
  await page.goto("/marketing");

  // Scoped to the return table: the same campaign is also a row in the
  // campaigns table, and an unscoped locator would match both.
  const row = page
    .getByTestId("campaign-return")
    .getByRole("row")
    .filter({ hasText: "Zero-budget test" });
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("No planned budget");
  await expect(row).not.toContainText(/NaN|0\.00×|Infinity/);
  await expect(page.locator("body")).not.toContainText(/undefined|NaN/);
});
