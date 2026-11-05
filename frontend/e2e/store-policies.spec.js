import { expect, test } from "@playwright/test";

test.skip(process.env.E2E_LIVE_API !== "1", "requires the ephemeral API/Postgres/Redis CI stack");

const keys = {
  exchange: /سياسة الاستبدال|Exchange policy/i,
  ordering: /سياسة الطلب|Ordering policy/i,
  cancellation: /سياسة الإلغاء|Cancellation policy/i,
};

// Six published-policy fields on one screen (four long-standing plus ordering,
// cancellation) and the deposit card, which reports "not configured" instead.
const UNWRITTEN = 6;

for (const [key, label] of Object.entries(keys)) {
  // The merchant writes the policy on the settings screen, it survives a reload
  // (so it really reached the database), and clearing it puts it back to
  // "not written yet".
  test(`the merchant can write, keep and remove the ${key} policy`, async ({ page }) => {
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    const email = `policies-e2e-${key}-${suffix}@example.com`;
    const password = `Policies-e2e-${key}-${suffix}!`;

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
    const field = page.getByRole("textbox", { name: label });
    await expect(field).toBeVisible();
    await expect(field).toHaveValue("");
    await expect(page.getByText(/لسه مكتوبتش|Not written yet/i)).toHaveCount(UNWRITTEN);

    const text = "الطلبات تتلغي خلال ساعة من تأكيد الشراء بدون أي خصم.";
    await field.fill(text);
    const saved = page.waitForResponse(
      (r) => new URL(r.url()).pathname === `/api/v1/ai/store-policies/${key}` && r.request().method() === "PUT",
    );
    // the policy card = the nearest ancestor of its textarea that also holds a button
    const card = field.locator("xpath=ancestor::*[.//button][1]");
    await card.getByRole("button", { name: /^حفظ$|^Save$/ }).click();
    expect((await saved).status()).toBe(200);
    await expect(page.getByText(/اتحفظت|Saved/i)).toBeVisible();
    await expect(page.getByText(/لسه مكتوبتش|Not written yet/i)).toHaveCount(UNWRITTEN - 1);

    // reload: the text must come back from the server, not from local state
    await page.reload();
    await expect(page.getByRole("textbox", { name: label })).toHaveValue(text);

    // clearing and saving removes it
    await page.getByRole("textbox", { name: label }).fill("");
    const removed = page.waitForResponse(
      (r) => new URL(r.url()).pathname === `/api/v1/ai/store-policies/${key}` && r.request().method() === "PUT",
    );
    await card.getByRole("button", { name: /مسح السياسة|Remove policy/i }).click();
    expect((await removed).status()).toBe(200);
    await expect(page.getByText(/لسه مكتوبتش|Not written yet/i)).toHaveCount(UNWRITTEN);

    expect(pageErrors).toEqual([]);
  });
}
