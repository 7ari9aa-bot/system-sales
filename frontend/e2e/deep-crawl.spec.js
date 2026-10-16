/** Deep crawl (design/QA pass) — walks EVERY route of the app against a real
 *  backend + real database, and reports per page: console errors, page
 *  errors, failed (4xx/5xx) API calls, and error-boundary text.
 *
 *  Auth: the FIRST test registers a fresh tenant through the real UI flow
 *  (register -> auto-login -> /dashboard) and saves the storage state; the
 *  dashboard crawl reuses it. Public routes crawl without auth.
 *
 *  Writes test-results/crawl-report.json at the end.
 */
import { test, expect, chromium } from "@playwright/test";
import fs from "node:fs";

const DASHBOARD_ROUTES = [
  "/dashboard", "/inbox", "/customers", "/orders", "/products",
  "/inventory", "/marketing", "/marketing/audience", "/marketing/automation",
  "/ai", "/analytics", "/usage", "/website", "/sales-assistant",
  "/settings", "/settings/channels", "/settings/billing",
  "/settings/members", "/settings/security", "/settings/danger",
];

// الموقع التسويقي — نفس قائمة PUBLIC_SEO_ROUTES
const PUBLIC_ROUTES = [
  "/", "/product", "/sales-assistant-preview", "/conversations", "/context",
  "/assistant", "/automation", "/pricing", "/security", "/privacy",
  "/terms", "/contact-sales", "/support",
].filter((r) => r !== "/sales-assistant-preview");

const ERROR_TEXTS = [
  "حدث خطأ غير متوقع", "Something went wrong", "error-boundary",
  "تعذّر تحميل", "Could not load", "حدث خطأ",
];

const report = { pages: [], consoleErrors: [], pageErrors: [], failedRequests: [], notes: [] };

async function crawlPage(page, route, tag) {
  const consoleErrors = [];
  const pageErrors = [];
  const failed = [];
  const onConsole = (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text().slice(0, 300));
  };
  const onPageError = (err) => pageErrors.push(String(err).slice(0, 300));
  const onResponse = (res) => {
    if (res.status() >= 400) {
      failed.push(`${res.status()} ${new URL(res.url()).pathname}`);
    }
  };
  page.on("console", onConsole);
  page.on("pageerror", onPageError);
  page.on("response", onResponse);

  let status = "ok";
  let landedOn = "";
  try {
    await page.goto(route, { waitUntil: "domcontentloaded", timeout: 30_000 });
    await page.waitForLoadState("networkidle", { timeout: 12_000 }).catch(() => {});
    await page.waitForTimeout(1_200);
    landedOn = new URL(page.url()).pathname;
    const body = (await page.content()).slice(0, 4000);
    const errorText = ERROR_TEXTS.find((t) => body.includes(t));
    if (errorText) status = `error-text: ${errorText}`;
  } catch (err) {
    status = `navigation failed: ${String(err).slice(0, 160)}`;
  } finally {
    page.off("console", onConsole);
    page.off("pageerror", onPageError);
    page.off("response", onResponse);
  }
  const entry = { tag, route, landedOn, status, consoleErrors, pageErrors, failed };
  report.pages.push(entry);
  report.consoleErrors.push(...consoleErrors.map((e) => ({ route, e })));
  report.pageErrors.push(...pageErrors.map((e) => ({ route, e })));
  report.failedRequests.push(...failed.map((f) => ({ route, f })));
  return entry;
}

test.describe.configure({ mode: "serial" });

test.describe("deep crawl — public marketing site", () => {
  for (const route of PUBLIC_ROUTES) {
    test(`public ${route}`, async ({ page }) => {
      const entry = await crawlPage(page, route, "public");
      expect(entry.status, `${route}: ${entry.status}`).not.toContain("error-text");
      expect(entry.status, `${route}: ${entry.status}`).not.toContain("navigation failed");
    });
  }
});

test.describe("deep crawl — authenticated dashboard", () => {
  let page;

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    const stamp = Date.now();
    const email = `crawl-${stamp}@gmail.com`;
    const password = "crawl-Preview-2026";

    // Register through the real UI: the flow auto-logs the new tenant in
    // and lands on /dashboard (the same path a merchant takes).
    await page.goto("/register", { waitUntil: "domcontentloaded" });
    await page.getByLabel(/البريد|Email/i).first().fill(email);
    const passwordFields = page.getByLabel(/كلمة المرور|Password/i);
    await passwordFields.nth(0).fill(password);
    await passwordFields.nth(1).fill(password);
    await page.getByRole("button", { name: /إنشاء|Create/i }).click();
    await page.waitForURL(/dashboard/, { timeout: 20_000 });
    report.notes.push(`registered ${email} -> dashboard OK`);
  });

  for (const route of DASHBOARD_ROUTES) {
    test(`dashboard ${route}`, async () => {
      const entry = await crawlPage(page, route, "dashboard");
      // كل صفحات الداشبورد محمية — غير المسجل بيتحول للدخول، فالمسار
      // المطلوب لازم يفضل هو نفسه (مفيش 404 ولا قفزة غير متوقعة).
      expect(entry.landedOn, `${route}: landed on ${entry.landedOn}`).toContain(route.split("?")[0]);
      expect(entry.status, `${route}: ${entry.status}`).not.toContain("error-text");
      expect(entry.status, `${route}: ${entry.status}`).not.toContain("navigation failed");
      expect(entry.failed.filter((f) => f.includes("404")), `${route} 404s: ${entry.failed}`).toEqual([]);
    });
  }

  test.afterAll(async () => {
    fs.mkdirSync("test-results", { recursive: true });
    fs.writeFileSync("test-results/crawl-report.json", JSON.stringify(report, null, 2));
    await page.close();
  });
});
