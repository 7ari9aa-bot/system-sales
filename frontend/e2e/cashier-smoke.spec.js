import { expect, test } from "@playwright/test";

// كل شاشات وحدة الكاشير (/cashier/*) يجب أن تُفتح بدون أخطاء React أو console،
// وبدون أن تتسرب أنماطها إلى صفحات النظام الرئيسي. الـ API مُحاكى (لا يوجد backend)؛ البيع الكامل الحقيقي يُختبر في live-api.spec.js.
const SCREENS = [
  "/cashier/pos", "/cashier/sales", "/cashier/sales/inv-1", "/cashier/returns", "/cashier/returns/log",
  "/cashier/exchanges", "/cashier/exchanges/log", "/cashier/products", "/cashier/products/new",
  "/cashier/products/p-1/edit", "/cashier/inventory", "/cashier/inventory/movements", "/cashier/inventory/stocktake",
  "/cashier/labels", "/cashier/suppliers", "/cashier/purchases", "/cashier/supplier-returns", "/cashier/shifts",
  "/cashier/expenses", "/cashier/reports", "/cashier/activity-log",
];

async function signIn(page) {
  await page.context().addCookies([{ name: "csrf_token", value: "test", url: "http://127.0.0.1:4173" }]);
  await page.route("**/api/v1/**", (route) => {
    const url = route.request().url();
    if (url.includes("/auth/me")) {
      return route.fulfill({ json: { id: "u1", email: "t@example.com", full_name: "Tester", role: "owner" } });
    }
    // The invoice screen reads ONE receipt (an object, not a list). Answer with the real
    // /pos/receipts/{id} shape so the detail screen renders instead of retrying forever.
    if (/\/pos\/receipts\/[^/?]+/.test(url)) {
      return route.fulfill({
        json: {
          receipt: { id: "inv-1", number: "INV-2026-0001", issued_at: "2026-10-20T10:00:00Z", change_amount: "0", tendered_amount: "100.00", kind: "sale" },
          order: { id: "o-1", number: "ORD-1", discount_total: "0", grand_total: "100.00", status: "paid" },
          lines: [{ variant_id: "v-1", title: "Test item", sku: "SKU-1", quantity: 1, unit_price: "100.00", total: "100.00", returned_qty: 0 }],
          tenders: [{ method: "cash", amount: "100.00" }],
        },
      });
    }
    return route.fulfill({ json: [] });
  });
}

test("every cashier screen renders without runtime errors", async ({ page }) => {
  await signIn(page);
  const failures = [];
  page.on("pageerror", (e) => failures.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error" && !/Failed to load resource|favicon|net::ERR|fonts\.g/.test(m.text())) failures.push(`console: ${m.text().slice(0, 160)}`);
  });

  for (const route of SCREENS) {
    const before = failures.length;
    await page.goto(route, { waitUntil: "networkidle" });
    // ننتظر ظهور الهيكل الخاص بالكاشير، وإلا فالصفحة لم تُركَّب أصلاً
    await expect(page.locator(".cashier-root"), `${route} must mount the cashier shell`).toBeVisible({ timeout: 8000 });
    // المحتوى الرئيسي (بدون القائمة الجانبية) لازم يكون فيه نص حقيقي، وإلا فالصفحة فاضية أو رسمت دالة مساعدة بالغلط
    const main = page.locator("main:has(.cashier-root)").first();
    await expect(main, `${route} must have a <main> region`).toBeVisible({ timeout: 8000 });
    const text = (await main.innerText()).trim();
    expect(text.length, `${route} main content too short: "${text.slice(0, 60)}"`).toBeGreaterThan(30);
    await expect(page.getByText("حصل خطأ والنظام وقف"), `${route} hit the error boundary`).toHaveCount(0);
    expect(page.url(), `${route} must not be redirected away`).toContain(route.split("/").slice(0, 3).join("/"));
    const added = failures.slice(before);
    expect(added, `${route} produced runtime errors`).toEqual([]);
  }
});

test("old /pos link lands on the new cashier and the sidebar highlights it", async ({ page }) => {
  await signIn(page);
  await page.goto("/pos", { waitUntil: "networkidle" });
  expect(new URL(page.url()).pathname).toBe("/cashier/pos");
  await expect(page.locator(".cashier-root")).toBeVisible();
});

test("cashier theme does not leak into the main app", async ({ page }) => {
  await signIn(page);
  await page.goto("/dashboard", { waitUntil: "networkidle" });
  const mainPrimary = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--primary").trim());
  expect(mainPrimary).not.toBe("26 94% 51%");
  const htmlSize = await page.evaluate(() => getComputedStyle(document.documentElement).fontSize);
  await page.goto("/cashier/pos", { waitUntil: "networkidle" });
  await page.goto("/dashboard", { waitUntil: "networkidle" });
  const after = await page.evaluate(() => getComputedStyle(document.documentElement).fontSize);
  expect(after).toBe(htmlSize);
});

test("cashier lives inside the main dashboard: one sidebar, cashier screens reachable from it", async ({ page }) => {
  await signIn(page);
  await page.goto("/cashier/pos", { waitUntil: "networkidle" });
  // سايدبار واحد فقط (النظام الأساسي)، مش اتنين.
  await expect(page.locator("aside")).toHaveCount(1);
  const aside = page.locator("aside").first();
  await expect(aside).toContainText("Inbox");            // بند من النظام الأساسي
  await expect(aside).toContainText("سجل المبيعات");     // شاشة كاشير في نفس القائمة
  await aside.getByRole("link", { name: "سجل المبيعات" }).click();
  await expect(page).toHaveURL(/\/cashier\/sales$/);
  await expect(page.locator("aside")).toHaveCount(1);
  await aside.getByRole("link", { name: "Home" }).click(); // الرجوع للداشبورد الأساسي
  await expect(page).toHaveURL(/\/dashboard/);
});
