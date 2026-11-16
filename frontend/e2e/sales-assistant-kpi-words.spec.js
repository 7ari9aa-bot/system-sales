import { expect, test } from "@playwright/test";
import { mockAssistantDay, threads, realExchange } from "./support/assistantDay.js";

// The number cards under an answer showed the server's internal words ("delivered revenue", "money",
// "15d"). The owner reads plain shop words, in the language of the page.
const card = (metric, window, unit = "money", value = "0") => ({ type: "kpi", metric, label: metric.replace(/_/g, " "), value, unit, window });

async function open(page, lang, blocks) {
  await page.setViewportSize({ width: 1366, height: 800 });
  const api = await mockAssistantDay(page, { lang });
  const [a, u] = realExchange("المقارنة طلعت صفر.", "قارن مبيعات الشهر ده باللي فات");
  a.structured_content = [{ type: "text", body: "المقارنة طلعت صفر." }, ...blocks];
  api.state.custom = [a, u];
  await page.goto("/sales-assistant");
  await page.waitForLoadState("networkidle");
  await page.getByText(threads[0].title, { exact: true }).first().click();
  await expect(page.getByText("المقارنة طلعت صفر.")).toBeVisible({ timeout: 8000 });
}
const chat = (page) => page.getByTestId("assistant-chat");

test("Arabic: the three cards from production read in plain shop words, with no English internals", async ({ page }) => {
  await open(page, "ar", [card("delivered_revenue", "15d"), card("delivered_revenue", "15d"), card("delivered_revenue", "46d")]);
  const text = await chat(page).innerText();
  expect(text).toContain("المبيعات المسلَّمة");
  expect(text).toContain("15 يوم");
  expect(text).toContain("46 يوم");
  for (const leak of ["delivered revenue", "delivered_revenue", "money", "15d", "46d"]) {
    expect(text, `leaked "${leak}"`).not.toContain(leak);
  }
});

test("English: the same cards read in plain English words", async ({ page }) => {
  await open(page, "en", [card("orders_placed", "7d", "count", "12"), card("collected_revenue", "1d", "EGP", "340.50")]);
  const text = await chat(page).innerText();
  expect(text).toContain("Orders placed");
  expect(text).toContain("Money collected");
  expect(text).toContain("7 days");
  expect(text).toContain("1 day");
  expect(text).toContain("EGP"); // a real currency is kept
  for (const leak of ["orders_placed", "orders placed", "7d", "count"]) expect(text).not.toContain(leak);
});

test("a metric the page has no word for is never shown as an identifier", async ({ page }) => {
  await open(page, "ar", [card("brand_new_metric", "3d")]);
  const text = await chat(page).innerText();
  expect(text).not.toContain("brand_new_metric");
  expect(text).toContain("brand new metric");
});
