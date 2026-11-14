import { expect, test } from "@playwright/test";
import { mockAssistantDay, threads } from "./support/assistantDay.js";

// "I send and nothing happens": a send must show the question at once, keep it if the server
// refuses, say what went wrong, and let the owner try again without retyping.
async function open(page, opts = {}) {
  await page.setViewportSize({ width: 1366, height: 800 });
  const api = await mockAssistantDay(page, { lang: "ar", ...opts });
  await page.goto("/sales-assistant");
  await page.waitForLoadState("networkidle");
  await page.getByText(threads[0].title, { exact: true }).first().click();
  await expect(page.getByText("سؤال رقم 30 عن المبيعات")).toBeVisible({ timeout: 8000 });
  return api;
}
const box = (page) => page.getByTestId("assistant-composer-field").locator("textarea");

test("my question shows in the chat immediately, before the server answers", async ({ page }) => {
  await open(page, { sendDelayMs: 1500 });
  await box(page).fill("سؤال جديد تماماً");
  await box(page).press("Enter");
  await expect(page.getByTestId("assistant-column").getByText("سؤال جديد تماماً")).toBeVisible({ timeout: 800 });
});

test("while waiting, the box is cleared and a working indicator shows", async ({ page }) => {
  await open(page, { sendDelayMs: 1500 });
  await box(page).fill("سؤال");
  await box(page).press("Enter");
  await expect(box(page)).toHaveValue("");
  await expect(page.getByTestId("assistant-pending")).toBeVisible();
});

test("if the server refuses, the text comes back to the box and an error explains it", async ({ page }) => {
  await open(page, { sendStatus: 500 });
  await box(page).fill("سؤال مهم");
  await box(page).press("Enter");
  await expect(page.getByTestId("assistant-send-error")).toBeVisible();
  await expect(box(page)).toHaveValue("سؤال مهم");
  await expect(page.getByTestId("assistant-column").getByText("سؤال مهم")).toHaveCount(0);
});

test("after a failure the owner can send again and it goes through", async ({ page }) => {
  const api = await open(page, { sendStatus: 500 });
  await box(page).fill("حاول تاني");
  await box(page).press("Enter");
  await expect(page.getByTestId("assistant-send-error")).toBeVisible();
  api.state.sendStatus = 200;
  await box(page).press("Enter");
  await expect.poll(() => api.sent.length).toBe(2);
  await expect(page.getByTestId("assistant-send-error")).toHaveCount(0);
});

test("the error goes away once the owner types something new", async ({ page }) => {
  await open(page, { sendStatus: 500 });
  await box(page).fill("س");
  await box(page).press("Enter");
  await expect(page.getByTestId("assistant-send-error")).toBeVisible();
  await box(page).fill("س2");
  await expect(page.getByTestId("assistant-send-error")).toHaveCount(0);
});

test("a failed new-chat creation also restores the text and explains", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 800 });
  await mockAssistantDay(page, { lang: "ar", createStatus: 500 });
  await page.goto("/sales-assistant");
  await page.waitForLoadState("networkidle");
  await box(page).fill("سؤال في محادثة جديدة");
  await box(page).press("Enter");
  await expect(page.getByTestId("assistant-send-error")).toBeVisible();
  await expect(box(page)).toHaveValue("سؤال في محادثة جديدة");
});

test("a send that works leaves no error and the question stays once", async ({ page }) => {
  const api = await open(page);
  await box(page).fill("سؤال ناجح");
  await box(page).press("Enter");
  await expect.poll(() => api.sent.length).toBe(1);
  await expect(page.getByTestId("assistant-send-error")).toHaveCount(0);
});
