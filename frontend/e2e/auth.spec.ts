import { expect, test } from "@playwright/test";
import { json, mockShell, seedAuth } from "./support";

/* W5 exit gate — auth.
 *
 * The app is Arabic-first, so assertions target ids/testids and roles rather
 * than the visible copy (which flips with the language toggle). The form
 * fields are addressed by their stable `id`, not their translated label. */

test("an unauthenticated visit to a dashboard route lands on the login page", async ({ page }) => {
  await page.goto("/dashboard");

  await expect(page).toHaveURL(/\/auth\/login$/);
  await expect(page.getByTestId("auth-login-card")).toBeVisible();
});

test("rejected credentials surface an inline alert", async ({ page }) => {
  await mockShell(page);
  await page.route("**/api/v1/auth/login", (route) =>
    route.fulfill({ status: 401, json: { error: { message: "invalid credentials" } } }),
  );

  await page.goto("/auth/login");
  await page.locator("#email").fill("owner@example.com");
  await page.locator("#password").fill("wrong-password");
  await page.getByTestId("submit-login").click();

  await expect(page.getByTestId("auth-error")).toBeVisible();
});

test("a successful login stores tokens and lands on the inbox", async ({ page }) => {
  await mockShell(page);
  await page.route("**/api/v1/auth/login", (route) =>
    json(route, { access_token: "live-access", refresh_token: "live-refresh" }),
  );
  await page.route("**/api/v1/conversations**", (route) =>
    json(route, { items: [], next_cursor: null }),
  );

  await page.goto("/auth/login");
  await page.locator("#email").fill("owner@example.com");
  await page.locator("#password").fill("correct-password");
  await page.getByTestId("submit-login").click();

  await expect(page).toHaveURL(/\/inbox$/);
  const stored = await page.evaluate(() => window.localStorage.getItem("sales_os_tokens"));
  expect(stored).toContain("live-access");
});

test("logging out clears the session and returns to the login page", async ({ page }) => {
  await seedAuth(page);
  await mockShell(page);

  await page.goto("/dashboard");
  await page.getByTestId("user-menu").click();
  await page.getByTestId("logout").click();

  await expect(page).toHaveURL(/\/auth\/login$/);
  const stored = await page.evaluate(() => window.localStorage.getItem("sales_os_tokens"));
  expect(stored).toBeNull();
});
