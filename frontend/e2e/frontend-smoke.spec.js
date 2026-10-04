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

test("an invalid cookie session refreshes once then clears the session", async ({ page, context }) => {
  let refreshRequests = 0;
  const authFailure = {
    error: {
      code: "permission_denied",
      message: "invalid token",
      retryable: false,
      request_id: "e2e-auth-expired",
    },
  };

  // The cookie session is HttpOnly: seeded via the browser context, not JS —
  // since the cookie wave there is nothing in localStorage to forge.
  const domain = new URL(process.env.BASE_URL || "http://127.0.0.1:4173").hostname;
  await context.addCookies([
    { name: "access_token", value: "expired-access-token", domain, path: "/", httpOnly: true },
    { name: "refresh_token", value: "expired-refresh-token", domain, path: "/", httpOnly: true },
    { name: "csrf_token", value: "e2e-csrf-value", domain, path: "/" },
  ]);
  await page.route("**/api/v1/auth/me", (route) => route.fulfill({
    status: 403,
    contentType: "application/json",
    body: JSON.stringify(authFailure),
  }));
  await page.route("**/api/v1/auth/refresh", (route) => {
    refreshRequests += 1;
    return route.fulfill({
      status: 403,
      contentType: "application/json",
      body: JSON.stringify(authFailure),
    });
  });

  await page.goto("/dashboard");

  await expect(page).toHaveURL(/\/login\?returnTo=%2Fdashboard/);
  await expect(page.getByRole("heading", { name: /مرحباً بعودتك|welcome back/i })).toBeVisible();
  await expect.poll(() => page.evaluate(() => localStorage.getItem("fihrist_tokens"))).toBeNull();
  expect(refreshRequests).toBe(1);
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

test("password-reset request stays generic and sends no saved bearer token", async ({ page }) => {
  let requestBody;
  let authorizationHeader;

  await page.route("**/api/v1/auth/password-reset/request", async (route) => {
    requestBody = route.request().postDataJSON();
    authorizationHeader = route.request().headers().authorization;
    await route.fulfill({
      status: 202,
      contentType: "application/json",
      headers: { "cache-control": "no-store" },
      body: JSON.stringify({ message: "If the account exists, instructions will be sent." }),
    });
  });

  await page.goto("/forgot-password");
  // A stale browser session must not be attached to public recovery requests.
  await page.evaluate(() => localStorage.setItem("fihrist_tokens", JSON.stringify({
    access_token: "stale-access-token",
    refresh_token: "stale-refresh-token",
  })));
  await page.getByLabel(/البريد الإلكتروني|email/i).fill("virtual-user@example.test");
  await page.getByRole("button", { name: /إرسال رابط الاستعادة|send reset link/i }).click();

  await expect(page.getByRole("status")).toBeVisible();
  await expect(page.getByRole("status")).toContainText(/مرتبطًا بحساب|associated with that email/i);
  expect(requestBody).toEqual({ email: "virtual-user@example.test" });
  expect(authorizationHeader).toBeUndefined();
});

test("password-reset link is removed from the URL and submits one new password", async ({ page }) => {
  const resetToken = "virtual-reset-token-0123456789abcdef0123456789abcdef";
  let requestBody;

  await page.route("**/api/v1/auth/password-reset/confirm", async (route) => {
    requestBody = route.request().postDataJSON();
    await route.fulfill({ status: 204 });
  });

  await page.goto(`/reset-password#token=${resetToken}`);
  await expect(page.locator("#new-password")).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.location.hash)).toBe("");
  await page.getByLabel(/كلمة المرور الجديدة|new password/i).fill("Virtual-pass-2026!");
  await page.getByLabel(/تأكيد كلمة المرور|confirm password/i).fill("Virtual-pass-2026!");
  await page.getByRole("button", { name: /حفظ كلمة المرور|save new password/i }).click();

  await expect(page.getByRole("status")).toContainText(/تم تحديث كلمة المرور|password has been updated/i);
  expect(requestBody).toEqual({ token: resetToken, password: "Virtual-pass-2026!" });
});
