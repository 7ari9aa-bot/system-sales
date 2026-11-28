import { expect, test } from "@playwright/test";
import { mockAssistantDay, messages, threads } from "./support/assistantDay.js";

// The owner wants to see how long the assistant thought, open each step to read the model's own
// thinking, and learn what made a slow answer slow. This plays the server's side: a running answer
// whose steps arrive with their measured seconds, then the finished answer with its summary.
const THREAD = threads[0].id;
const QUESTION = "قارنلي مبيعات الشهر ده بالشهر اللي فات";
const base = () => [...messages(THREAD)].reverse();
const userRow = {
  id: "q-new", thread_id: THREAD, sequence_no: 61, role: "user", status: "completed",
  content: QUESTION, structured_content: null, run_id: null, analysis_id: null, error_code: null,
  created_at: "2026-11-16T10:00:00Z", progress: null, trace: null,
};
const row = (over) => ({
  id: "a-new", thread_id: THREAD, sequence_no: 62, role: "assistant", status: "generating",
  content: "", structured_content: null, run_id: null, analysis_id: null, error_code: null,
  created_at: "2026-11-16T10:00:01Z", progress: null, trace: null, ...over,
});
const ev = (id, kind, phase, extra = {}) => ({ id, kind, phase, at_ms: 0, ...extra });
const ROUND1 = [
  ev(1, "model", "start", { purpose: "answer" }),
  ev(1, "model", "end", { ms: 4200, ok: true, tokens_out: 80, reasoning: "السؤال عن مقارنة، هنادي أداة المبيعات مرتين.", answered: false }),
];
const READ = [ev(2, "tool", "start", { tool: "si_metric", step: "بقرا مبيعاتك" }), ev(2, "tool", "end", { ms: 350, ok: true })];
const ROUND2 = [
  ev(3, "model", "start", { purpose: "answer" }),
  ev(3, "model", "end", { ms: 6100, ok: true, tokens_out: 900, reasoning: "الرقمين جاهزين، هكتب المقارنة.", reasoning_cut: true, answered: true }),
];
const REWRITE = [
  ev(4, "model", "start", { purpose: "rewrite" }),
  ev(4, "model", "end", { ms: 5300, ok: true, tokens_out: 200, reasoning: null, answered: true }),
];
const SUMMARY = {
  id: 0, kind: "summary", phase: "end", total_ms: 17000, model_ms: 15600, tools_ms: 350, other_ms: 1050,
  rounds: 3, tool_calls: 1, tokens_in: 9000, tokens_out: 1180,
  reasons: ["الرد اترفض في مراجعة الأرقام فاتكتب تاني (5.3 ث)", "كتب كتير في جولة واحدة (حوالي 900 توكن في 6.1 ث)"],
};

async function start(page) {
  await page.setViewportSize({ width: 1366, height: 800 });
  const api = await mockAssistantDay(page, { lang: "ar", sendDelayMs: 9000 });
  await page.goto("/sales-assistant");
  await page.waitForLoadState("networkidle");
  await page.getByText(threads[0].title, { exact: true }).first().click();
  await expect(page.getByText("سؤال رقم 30 عن المبيعات")).toBeVisible({ timeout: 8000 });
  return api;
}
const box = (page) => page.getByTestId("assistant-composer-field").locator("textarea");
const ask = async (page) => {
  await box(page).fill(QUESTION);
  await box(page).press("Enter");
};

test("a running answer lists each step with its measured seconds and opens a round to its thinking", async ({ page }) => {
  const api = await start(page);
  await ask(page);
  api.state.custom = [row({ trace: [...ROUND1, ...READ, ev(3, "model", "start", { purpose: "answer" })] }), userRow, ...base()];
  const steps = page.getByTestId("assistant-trace-step");
  await expect(steps).toHaveCount(3, { timeout: 6000 });
  await expect(steps.nth(0)).toContainText("تفكير 1");
  await expect(steps.nth(0)).toContainText("4.2 ث");
  await expect(steps.nth(1)).toContainText("بقرا مبيعاتك");
  await expect(steps.nth(1)).toContainText("0.3 ث");
  // the round still running has no measured value yet, so it is open and counting
  await expect(steps.nth(2)).toHaveAttribute("data-done", "false");
  // the round still running shows seconds counting up, not a measured value and not a frozen 0.0
  const seconds = async () => parseFloat((await steps.nth(2).innerText()).match(/(\d+\.\d)/)[1]);
  await page.waitForTimeout(600);
  const first = await seconds();
  await page.waitForTimeout(900);
  expect(await seconds()).toBeGreaterThan(first);
  // the first round opens to the model's own words, the read does not open
  await expect(page.getByTestId("assistant-trace-reasoning")).toHaveCount(0);
  await steps.nth(0).getByRole("button").click();
  await expect(page.getByTestId("assistant-trace-reasoning")).toHaveText("السؤال عن مقارنة، هنادي أداة المبيعات مرتين.");
  await expect(steps.nth(1).getByRole("button")).toBeDisabled();
  await steps.nth(0).getByRole("button").click();
  await expect(page.getByTestId("assistant-trace-reasoning")).toHaveCount(0);
});

test("the finished answer folds to 'thought for N s' and says why it was slow", async ({ page }) => {
  const api = await start(page);
  await ask(page);
  api.state.custom = [row({ trace: [...ROUND1, ...READ, ...ROUND2, ...REWRITE] }), userRow, ...base()];
  await expect(page.getByTestId("assistant-trace-step")).toHaveCount(4, { timeout: 6000 });
  api.state.custom = [
    row({ status: "completed", content: "الإيراد ارتفع.", trace: [...ROUND1, ...READ, ...ROUND2, ...REWRITE, SUMMARY] }),
    userRow, ...base(),
  ];
  const toggle = page.getByTestId("assistant-trace-toggle");
  await expect(toggle).toContainText("فكّر لمدة 15.6 ث", { timeout: 8000 });
  await expect(page.getByTestId("assistant-pending")).toHaveCount(0);
  // folded: no step list until the owner opens it
  await expect(page.getByTestId("assistant-trace-steps")).toHaveCount(0);
  await toggle.click();
  const steps = page.getByTestId("assistant-trace-step");
  await expect(steps).toHaveCount(4);
  await expect(steps.nth(3)).toContainText("إعادة كتابة الرد");
  await expect(steps.nth(3)).toContainText("5.3 ث");
  // a cut thinking says it was cut
  await steps.nth(2).getByRole("button").click();
  await expect(page.getByTestId("assistant-trace-reasoning")).toContainText("التفكير أطول من ذلك وتم اختصاره هنا");
  await expect(page.getByTestId("assistant-trace-summary")).toContainText("الإجمالي 17.0 ث");
  await expect(page.getByTestId("assistant-trace-why")).toContainText("اترفض في مراجعة الأرقام");
  await expect(page.getByTestId("assistant-trace-why")).toContainText("كتب كتير");
});

test("an answer with nothing slow says so, and an old answer with no trace shows no panel", async ({ page }) => {
  const api = await start(page);
  await ask(page);
  const quick = { ...SUMMARY, total_ms: 6000, model_ms: 5500, tools_ms: 300, other_ms: 200, reasons: [] };
  api.state.custom = [
    row({ status: "completed", content: "تمام.", trace: [...ROUND1, quick] }), userRow, ...base(),
  ];
  await page.getByTestId("assistant-trace-toggle").click({ timeout: 8000 });
  await expect(page.getByTestId("assistant-trace-why")).toHaveCount(0);
  await expect(page.getByTestId("assistant-trace-summary")).toContainText("لم يبطئ هذا الرد أي شيء");
  // the answers already in the thread were written before tracing existed: no panel on them
  await expect(page.getByTestId("assistant-trace")).toHaveCount(1);
});

test("the reply-speed panel shows the measured split, the causes and the slowest replies", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 800 });
  await mockAssistantDay(page, { lang: "ar" });
  const asked = [];
  // later routes win in Playwright, so this sits on top of the day mock
  await page.route("**/api/v1/ai/sales-chat/timing**", (r) => {
    const days = new URL(r.request().url()).searchParams.get("days");
    asked.push(days);
    if (days === "1") return r.fulfill({ json: { days: 1, answers: 0, untraced: 0, median_total_ms: 0, avg_total_ms: 0, avg_model_ms: 0, avg_tools_ms: 0, avg_other_ms: 0, avg_rounds: 0, causes: [], slowest: [] } });
    return r.fulfill({
      json: {
        days: 7, answers: 12, untraced: 3, median_total_ms: 17200, avg_total_ms: 21000, avg_model_ms: 16400,
        avg_tools_ms: 600, avg_other_ms: 4000, avg_rounds: 3.1,
        causes: [{ code: "repeat_source", text: "رجع لنفس المصدر كذا مرة بطلبات مختلفة", answers: 7 }],
        slowest: [{ question: "قارن مبيعات الشهر", total_ms: 53900, model_ms: 48000, rounds: 5, reasons: ["رجع لنفس المصدر 6 مرات بطلبات مختلفة (si_metric)"] }],
      },
    });
  });
  await page.goto("/sales-assistant");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("timing-open").click();
  const panel = page.getByTestId("timing-panel");
  await expect(panel.getByTestId("timing-totals")).toContainText("17.2 ث");
  await expect(panel.getByTestId("timing-totals")).toContainText("16.4 ث");
  await expect(panel).toContainText("12 رد، ومتوسط 3.1 جولة");
  await expect(panel.getByTestId("timing-causes")).toContainText("في 7 من 12");
  await expect(panel.getByTestId("timing-slowest")).toContainText("قارن مبيعات الشهر");
  await expect(panel.getByTestId("timing-slowest")).toContainText("53.9 ث");
  await expect(panel).toContainText("3 ردود كُتبت قبل القياس فلم تُحتسب");
  await panel.getByTestId("timing-range-1").click();
  await expect(panel.getByTestId("timing-empty")).toBeVisible();
  expect(asked).toEqual(["7", "1"]);
  // one side panel at a time: opening memory closes this one
  await page.getByRole("button", { name: /الذاكرة|ذاكرة/ }).first().click();
  await expect(page.getByTestId("timing-panel")).toHaveCount(0);
});
