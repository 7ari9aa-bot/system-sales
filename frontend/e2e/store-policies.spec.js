import { expect, test } from "@playwright/test";

test.skip(process.env.E2E_LIVE_API !== "1", "requires the ephemeral API/Postgres/Redis CI stack");

// The merchant writes the exchange policy on the settings screen, it survives a reload (so it
// really reached the database), and clearing it puts the policy back to "not written yet".
test("the merchant can write, keep and remove a store policy", async ({ page }) => {
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  const email = `policies-e2e-${suffix}@example.com`;
  const password = `Policies-e2e-${suffix}!`;

  await page.goto("/register");
  await page.getByLabel(/البريد الإلكتروني|email/i).fill(email);
  await page.getByLabel(/^كلمة المرور$|^password$/i).fill(password);
  await page.getByLabel(/تأكيد كلمة المرور|confirm password/i).fill(password);
  const login = page.waitForResponse(
    (r) => new URL(r.url()).pathname === "/api/v1/auth/login" && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: /إنشاء الحساب|create account/i }).click();
  expect((await login).status()).toBe(200);
  await expect(page).toHaveURL(/\/dashboard$/);

  await page.goto("/settings/policies");
  const exchange = page.getByRole("textbox", { name: /سياسة الاستبدال|Exchange policy/i });
  await expect(exchange).toBeVisible();
  await expect(exchange).toHaveValue("");
  // four cards, all unwritten on a new store
  await expect(page.getByText(/لسه مكتوبتش|Not written yet/i)).toHaveCount(4);

  const text = "الاستبدال خلال 14 يوم من الشراء بشرط وجود الفاتورة.";
  await exchange.fill(text);
  const saved = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname === "/api/v1/ai/store-policies/exchange" &&
      r.request().method() === "PUT",
  );
  // the exchange card = the nearest ancestor of its textarea that also holds a button
  const card = exchange.locator("xpath=ancestor::*[.//button][1]");
  await card.getByRole("button", { name: /^حفظ$|^Save$/ }).click();
  expect((await saved).status()).toBe(200);
  await expect(page.getByText(/اتحفظت|Saved/i)).toBeVisible();
  await expect(page.getByText(/لسه مكتوبتش|Not written yet/i)).toHaveCount(3);

  // reload: the text must come back from the server, not from local state
  await page.reload();
  await expect(page.getByRole("textbox", { name: /سياسة الاستبدال|Exchange policy/i })).toHaveValue(text);

  // clearing and saving removes it
  await page.getByRole("textbox", { name: /سياسة الاستبدال|Exchange policy/i }).fill("");
  const removed = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname === "/api/v1/ai/store-policies/exchange" &&
      r.request().method() === "PUT",
  );
  await card.getByRole("button", { name: /مسح السياسة|Remove policy/i }).click();
  expect((await removed).status()).toBe(200);
  await expect(page.getByText(/لسه مكتوبتش|Not written yet/i)).toHaveCount(4);

  expect(pageErrors).toEqual([]);
});
