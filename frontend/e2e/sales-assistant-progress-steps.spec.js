import { expect, test } from "@playwright/test";
import { mockAssistantDay, messages, threads } from "./support/assistantDay.js";

// While a question runs the owner used to see three bouncing dots and nothing else for about
// fifteen seconds. The server now records each thing the assistant really starts, and the page
// shows those lines as they arrive. This plays the server's side of one slow question: the
// question is saved first, the answer row is `generating`, a step appears, then another, then the
// answer lands.
const THREAD = threads[0].id;
const QUESTION = "قارنلي مبيعات الشهر ده بالشهر اللي فات";
const base = () => [...messages(THREAD)].reverse(); // newest first, as the API returns it
const userRow = {
  id: "q-new", thread_id: THREAD, sequence_no: 61, role: "user", status: "completed",
  content: QUESTION, structured_content: null, run_id: null, analysis_id: null, error_code: null,
  created_at: "2026-11-16T10:00:00Z", progress: null,
};
const openRow = (progress) => ({
  id: "a-new", thread_id: THREAD, sequence_no: 62, role: "assistant", status: "generating",
  content: "", structured_content: null, run_id: null, analysis_id: null, error_code: null,
  created_at: "2026-11-16T10:00:01Z", progress,
});
const doneRow = {
  ...openRow(["بقرا مبيعاتك", "بشوف المخزون"]), status: "completed",
  content: "الإيراد المسلَّم ارتفع عن الشهر اللي فات.",
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

test("each step shows as the server records it, in order, and the earlier ones read as done", async ({ page }) => {
  const api = await start(page);
  await ask(page);
  // the question is saved and the answer is open, nothing recorded yet: the dots, no step lines
  api.state.custom = [openRow(null), userRow, ...base()];
  await expect(page.getByTestId("assistant-pending")).toBeVisible();
  await expect(page.getByTestId("assistant-step")).toHaveCount(0);

  api.state.custom = [openRow(["بقرا مبيعاتك"]), userRow, ...base()];
  await expect(page.getByTestId("assistant-step")).toHaveCount(1, { timeout: 6000 });
  await expect(page.getByTestId("assistant-step").first()).toHaveText("بقرا مبيعاتك");
  await expect(page.getByTestId("assistant-step").first()).toHaveAttribute("data-done", "false");

  api.state.custom = [openRow(["بقرا مبيعاتك", "بشوف المخزون"]), userRow, ...base()];
  await expect(page.getByTestId("assistant-step")).toHaveCount(2, { timeout: 6000 });
  await expect(page.getByTestId("assistant-step").nth(0)).toHaveAttribute("data-done", "true");
  await expect(page.getByTestId("assistant-step").nth(1)).toHaveAttribute("data-done", "false");
  await expect(page.getByTestId("assistant-step").nth(1)).toHaveText("بشوف المخزون");
});

test("the question and the waiting answer are each drawn once while polling", async ({ page }) => {
  const api = await start(page);
  await ask(page);
  api.state.custom = [openRow(["بقرا مبيعاتك"]), userRow, ...base()];
  await expect(page.getByTestId("assistant-step")).toHaveCount(1, { timeout: 6000 });
  const column = page.getByTestId("assistant-column");
  // the server now returns my question, so the temporary copy must have gone
  await expect(column.getByText(QUESTION, { exact: true })).toHaveCount(1);
  // and the open answer is not drawn once as a row and again as the indicator
  await expect(page.getByTestId("assistant-pending")).toHaveCount(1);
});

test("when the answer lands the steps are gone and the reply is shown", async ({ page }) => {
  const api = await start(page);
  await ask(page);
  api.state.custom = [openRow(["بقرا مبيعاتك", "بشوف المخزون"]), userRow, ...base()];
  await expect(page.getByTestId("assistant-step")).toHaveCount(2, { timeout: 6000 });
  api.state.custom = [doneRow, userRow, ...base()];
  // the held POST finishes (9 s) and the list is read once more
  await expect(page.getByText("الإيراد المسلَّم ارتفع عن الشهر اللي فات.")).toBeVisible({ timeout: 14000 });
  await expect(page.getByTestId("assistant-pending")).toHaveCount(0);
  await expect(page.getByTestId("assistant-step")).toHaveCount(0);
});

test("no polling happens while nothing is being asked", async ({ page }) => {
  await start(page);
  let reads = 0;
  page.on("request", (r) => {
    if (r.method() === "GET" && /\/ai\/sales-chat\/threads\/[^/]+\/messages/.test(r.url())) reads += 1;
  });
  await page.waitForTimeout(4500); // three poll periods if it were running
  expect(reads).toBe(0);
});

test("a question that runs no tool shows only the dots, with no invented step", async ({ page }) => {
  const api = await start(page);
  await ask(page);
  api.state.custom = [openRow(null), userRow, ...base()];
  await expect(page.getByTestId("assistant-pending")).toBeVisible();
  await page.waitForTimeout(3500);
  await expect(page.getByTestId("assistant-step")).toHaveCount(0);
});
