import { expect, test } from "@playwright/test";
import { json, mockShell, seedAuth, serverError } from "./support";

/* W5 exit gate — failure states.
 *
 * The gate explicitly requires that a mocked 500 renders the shared error
 * state (`role="alert"` + retry) rather than crashing or blanking the shell.
 * These two specs assert the alert AND that the surrounding chrome is still
 * mounted, which is the part a page-local assertion would miss.
 *
 * The alert is addressed by testid: Next's App Router also renders a
 * `role="alert"` route announcer, so a bare role lookup is ambiguous. */

test("a 500 on the orders API renders an alert and keeps the shell mounted", async ({ page }) => {
  await seedAuth(page);
  await mockShell(page);
  await page.route("**/api/v1/customers**", (route) => json(route, { items: [] }));
  await page.route("**/api/v1/products**", (route) => json(route, []));
  await page.route("**/api/v1/orders**", (route) => serverError(route, "orders exploded"));

  await page.goto("/orders");

  const alert = page.getByTestId("error-state");
  await expect(alert).toBeVisible();
  await expect(alert).toContainText("orders exploded");
  await expect(alert.getByRole("button")).toBeVisible();
  // The shell did not unmount around the failing page.
  await expect(page.getByTestId("nav-orders")).toBeVisible();
  await expect(page.getByTestId("user-menu")).toBeVisible();
});

test("an API that fails every endpoint does not crash the shell", async ({ page }) => {
  await seedAuth(page);
  await page.route("**/api/v1/**", (route) => serverError(route, "all endpoints down"));

  await page.goto("/dashboard");

  // Owner IA 2026-09-27: the dashboard nav item is now "Overview".
  await expect(page.getByTestId("nav-overview")).toBeVisible();
  // The Overview is a composite: every widget owns its own error state, so a
  // full outage surfaces several alerts at once — one suffices for this claim.
  await expect(page.getByTestId("error-state").first()).toBeVisible();
  await expect(page.getByTestId("health-indicator")).toBeVisible();
});

/* Three pages gated on `isError` and then rendered the ERROR through the empty
 * state — the shared `EmptyState` with the failure message as its title and no
 * retry. Visually that is "you have nothing here", which is a different claim
 * about the merchant's data than "the server could not answer", and it is the
 * claim they acted on. They now render the same retryable alert the rest of the
 * dashboard uses, so the assertions below are the alert, its message, its retry,
 * and that the retry actually recovers the page. */

const FORMERLY_LYING_PAGES: {
  path: string;
  nav: string;
  /** pattern -> the body it returns once the outage is over */
  endpoints: [string, unknown][];
}[] = [
  {
    path: "/marketing",
    nav: "nav-marketing",
    endpoints: [
      ["**/api/v1/marketing/campaigns**", { items: [] }],
      ["**/api/v1/analytics/summary**", { orders_summary: null }],
    ],
  },
  {
    path: "/ai",
    nav: "nav-ai",
    endpoints: [
      ["**/api/v1/ai/knowledge**", { items: [] }],
      ["**/api/v1/ai/agents**", []],
      [
        "**/api/v1/ai/usage/summary**",
        { summary: [], totals: { cost: "0.0000", tokens_in: 0, tokens_out: 0 } },
      ],
    ],
  },
  {
    path: "/settings",
    nav: "nav-settings",
    endpoints: [
      ["**/api/v1/invitations**", []],
      ["**/api/v1/integrations**", []],
    ],
  },
];

for (const { path, nav, endpoints } of FORMERLY_LYING_PAGES) {
  test(`${path} renders a failed read as an error with a working retry, not as an empty list`, async ({
    page,
  }) => {
    let down = true;
    await seedAuth(page);
    await mockShell(page);
    for (const [pattern, body] of endpoints) {
      await page.route(pattern, (route) =>
        down ? serverError(route, `${pattern} is down`) : json(route, body),
      );
    }

    await page.goto(path);

    const alert = page.getByTestId("error-state");
    await expect(alert).toBeVisible();
    await expect(alert).toContainText("is down");
    await expect(alert.getByRole("button")).toBeVisible();
    await expect(page.getByTestId(nav)).toBeVisible();

    down = false;
    await alert.getByRole("button").click();

    await expect(alert).toHaveCount(0);
    await expect(page.getByTestId(nav)).toBeVisible();
  });
}
