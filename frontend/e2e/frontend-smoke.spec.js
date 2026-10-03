import { expect, test } from "@playwright/test";

const PUBLIC_ROUTES = [
  "/",
  "/product",
  "/conversations",
  "/context",
  "/assistant",
  "/automation",
  "/pricing",
  "/security",
  "/privacy",
  "/terms",
  "/contact-sales",
  "/support",
  "/login",
  "/register",
  "/forgot-password",
  "/reset-password",
  "/accept-invitation",
];

test("every public and authentication route survives a production refresh", async ({ page }) => {
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  for (const route of PUBLIC_ROUTES) {
    const response = await page.goto(route, { waitUntil: "domcontentloaded" });
    expect(response?.status(), `${route} must be served by the SPA fallback`).toBe(200);
    await expect(page.locator("body")).not.toBeEmpty();
    await expect(page.locator("#root")).not.toBeEmpty();
  }

  expect(pageErrors, "route navigation must not throw in React").toEqual([]);
});

test("login exposes labeled credentials and a working registration link", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: /مرحباً بعودتك|welcome back/i })).toBeVisible();
  await expect(page.getByLabel(/البريد الإلكتروني|email/i)).toBeVisible();
  await expect(page.getByLabel(/كلمة المرور|password/i)).toBeVisible();
  const registrationLink = page.getByRole("link", { name: /أنشئ واحداً|create one/i });
  const registrationUrl = new URL(await registrationLink.getAttribute("href"), page.url());
  expect(registrationUrl.pathname).toBe("/register");
  if (registrationUrl.searchParams.has("returnTo")) {
    expect(registrationUrl.searchParams.get("returnTo")).toMatch(/^\//);
  }
});

test("protected dashboard and settings deep links return an anonymous user to login", async ({ page }) => {
  for (const route of ["/dashboard", "/inbox", "/settings/channels", "/settings/security"]) {
    await page.goto(route, { waitUntil: "domcontentloaded" });
    await expect(page).toHaveURL(/\/login\?returnTo=/);
    await expect(page.getByRole("heading", { name: /مرحباً بعودتك|welcome back/i })).toBeVisible();
  }
});

test("login and pricing fit a mobile viewport without horizontal scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const route of ["/login", "/pricing"]) {
    await page.goto(route, { waitUntil: "domcontentloaded" });
    const widths = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      content: document.documentElement.scrollWidth,
    }));
    expect(widths.content, `${route} must not overflow horizontally`).toBeLessThanOrEqual(
      widths.viewport,
    );
  }
});
