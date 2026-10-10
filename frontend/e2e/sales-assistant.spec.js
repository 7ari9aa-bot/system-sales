/** /sales-assistant e2e — the UI contract only. The sales-chat backend is
 *  route-mocked (the spec tests UI, not the model); auth still runs the real
 *  register→login flow against the ephemeral CI stack, exactly like
 *  live-api.spec.js. CI-only verdicts: this sandbox cannot bind ports. */

import { expect, test } from "@playwright/test";

test.skip(process.env.E2E_LIVE_API !== "1", "requires the ephemeral API/Postgres/Redis CI stack");

const THREAD_ID = "11111111-1111-4111-8111-111111111111";
const THREAD = {
  id: THREAD_ID,
  title: "تقرير الشهر",
  status: "active",
  context: {},
  created_at: "2026-10-10T10:00:00Z",
  updated_at: "2026-10-10T10:05:00Z",
  last_message_at: "2026-10-10T10:05:00Z",
};
const USER_TURN = {
  id: "22222222-2222-4222-8222-222222222222",
  thread_id: THREAD_ID,
  sequence_no: 1,
  role: "user",
  status: "completed",
  content: "قارن مبيعات الشهر ده باللي فات.",
  structured_content: null,
  run_id: null,
  analysis_id: null,
  error_code: null,
  created_at: "2026-10-10T10:04:00Z",
};
const ANSWER = {
  id: "33333333-3333-4333-8333-333333333333",
  thread_id: THREAD_ID,
  sequence_no: 2,
  role: "assistant",
  status: "completed",
  content: "الإيراد ارتفع 12 بالمئة مقارنة بالشهر الماضي.",
  structured_content: [
    { type: "text", body: "الإيراد ارتفع 12 بالمئة مقارنة بالشهر الماضي." },
    { type: "kpi", metric: "revenue", label: "الإيراد", value: "12500.00", unit: "EGP", window: "30d" },
    {
      type: "findings",
      items: [
        {
          statement: "الإيراد ارتفع",
          type: "FACT",
          relationship: "OBSERVED",
          confidence: "HIGH",
          confidence_reasons: [],
          evidence_refs: ["F1"],
        },
      ],
    },
    { type: "refs", analysis_id: "44444444-4444-4444-8444-444444444444", run_id: "55555555-5555-4555-8555-555555555555" },
  ],
  run_id: "55555555-5555-4555-8555-555555555555",
  analysis_id: "44444444-4444-4444-8444-444444444444",
  error_code: null,
  created_at: "2026-10-10T10:05:00Z",
};

const mockSalesChat = (page) => {
  page.route("**/api/v1/ai/sales-chat/threads", (route) => {
    if (route.request().method() === "POST") {
      return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(THREAD) });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([THREAD]) });
  });
  page.route(`**/api/v1/ai/sales-chat/threads/${THREAD_ID}/messages`, (route) => {
    if (route.request().method() === "POST") {
      return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(ANSWER) });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([USER_TURN, ANSWER]),
    });
  });
};

const registerAndStayLoggedIn = async (page) => {
  const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  const email = `chat-e2e-${suffix}@example.com`;
  const password = `Chat-e2e-${suffix}!`;
  await page.goto("/register");
  await page.getByLabel(/البريد الإلكتروني|email/i).fill(email);
  await page.getByLabel(/^كلمة المرور$|^password$/i).fill(password);
  await page.getByLabel(/تأكيد كلمة المرور|confirm password/i).fill(password);
  await page.getByRole("button", { name: /إنشاء الحساب|create account/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 20_000 });
};

test("sales assistant: ask, render blocks, survive reload, list actions, both languages", async ({ page }) => {
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  mockSalesChat(page);
  await registerAndStayLoggedIn(page);

  // AR pass (the default register flow lands in Arabic strings either way —
  // pin the language explicitly so both passes are deterministic).
  await page.addInitScript(() => localStorage.setItem("salesos.lang", "ar"));
  await page.goto("/sales-assistant", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: "مساعد المبيعات" })).toBeVisible();

  // Send an example question → the mocked pair renders: user turn + answer
  // with the kpi block and the evidence refs badges.
  await page.locator("button", { hasText: "قارن مبيعات الشهر ده باللي فات." }).first().click();
  await expect(page.getByText("الإيراد ارتفع 12 بالمئة مقارنة بالشهر الماضي.", { exact: true })).toBeVisible();
  await expect(page.getByText("12500.00", { exact: false })).toBeVisible();
  await expect(page.getByText("تحليل محفوظ", { exact: true })).toBeVisible();

  // Thread list carries the (mocked) thread; reload keeps the history.
  await expect(page.getByText("تقرير الشهر", { exact: true })).toBeVisible();
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.getByText("الإيراد ارتفع 12 بالمئة مقارنة بالشهر الماضي.", { exact: true })).toBeVisible();

  // List actions exist (hover-revealed, so force-assert them).
  const firstThreadRow = page.locator("li", { hasText: "تقرير الشهر" }).first();
  await expect(firstThreadRow.getByTitle("إعادة تسمية")).toBeAttached();
  await expect(firstThreadRow.getByTitle("أرشفة")).toBeAttached();
  await expect(firstThreadRow.getByTitle("حذف")).toBeAttached();

  // EN pass — same surface, English strings.
  await page.addInitScript(() => localStorage.setItem("salesos.lang", "en"));
  await page.goto("/sales-assistant", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Sales Assistant" })).toBeVisible();
  await expect(page.getByText("الإيراد ارتفع 12 بالمئة مقارنة بالشهر الماضي.", { exact: true })).toBeVisible();

  // The neighboring surfaces must be untouched by the new page.
  for (const path of ["/ai", "/analytics", "/inbox"]) {
    const response = await page.goto(path, { waitUntil: "domcontentloaded" });
    expect(response?.status(), `${path} must still render`).toBe(200);
    await expect(page.locator("#root")).not.toBeEmpty();
  }

  expect(pageErrors, "the chat page must not throw in React").toEqual([]);
});
