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

  await expect(page.getByTestId("nav-dashboard")).toBeVisible();
  await expect(page.getByTestId("error-state")).toBeVisible();
  await expect(page.getByTestId("health-indicator")).toBeVisible();
});
