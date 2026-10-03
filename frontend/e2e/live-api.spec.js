import { expect, test } from "@playwright/test";

test.skip(process.env.E2E_LIVE_API !== "1", "requires the ephemeral API/Postgres/Redis CI stack");

test("real registration, dashboard reads, orders, and logout work end to end", async ({ page }) => {
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  const email = `live-e2e-${suffix}@example.test`;
  const password = `Live-e2e-${suffix}!`;

  await page.goto("/register");
  await page.getByLabel(/البريد الإلكتروني|email/i).fill(email);
  await page.getByLabel(/^كلمة المرور$|^password$/i).fill(password);
  await page.getByLabel(/تأكيد كلمة المرور|confirm password/i).fill(password);

  const registerResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/v1/auth/register" && response.request().method() === "POST";
  });
  const loginResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/v1/auth/login" && response.request().method() === "POST";
  });
  const dashboardResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/v1/analytics/dashboard" && response.request().method() === "GET";
  });

  await page.getByRole("button", { name: /إنشاء الحساب|create account/i }).click();

  expect((await registerResponsePromise).status()).toBe(201);
  expect((await loginResponsePromise).status()).toBe(200);
  await expect(page).toHaveURL(/\/dashboard$/);

  const dashboardResponse = await dashboardResponsePromise;
  expect(dashboardResponse.status()).toBe(200);
  const dashboard = await dashboardResponse.json();
  expect(dashboard).toEqual(expect.objectContaining({
    orders: expect.any(Object),
    conversations: expect.any(Object),
    daily_orders: expect.any(Array),
    revenue_by_source: expect.any(Array),
  }));
  await expect(page.getByRole("button", { name: /تسجيل الخروج|sign out/i })).toBeVisible();

  const ordersResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/v1/orders"
      && url.searchParams.get("limit") === "100"
      && response.request().method() === "GET";
  });
  await page.getByRole("link", { name: /^orders$|^الطلبات$/i }).click();
  await expect(page).toHaveURL(/\/orders$/);
  const ordersResponse = await ordersResponsePromise;
  expect(ordersResponse.status()).toBe(200);
  expect(await ordersResponse.json()).toEqual(expect.objectContaining({ items: expect.any(Array) }));

  const logoutResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/v1/auth/logout" && response.request().method() === "POST";
  });
  await page.getByRole("button", { name: /تسجيل الخروج|sign out/i }).click();
  expect((await logoutResponsePromise).status()).toBe(204);
  await expect(page).toHaveURL(/\/login$/);
  await expect.poll(() => page.evaluate(() => localStorage.getItem("fihrist_tokens"))).toBeNull();

  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login\?returnTo=/);
  expect(pageErrors).toEqual([]);
});
