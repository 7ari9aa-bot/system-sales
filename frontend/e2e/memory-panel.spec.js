import { expect, test } from "@playwright/test";

// The assistant's memory screen against a STATEFUL stand-in for the API: it keeps the notes, refuses
// what the real server refuses, and answers with the real error shape, so what is checked here is the
// screen's behaviour (add, refusal, edit, delete one, delete all, switch off), not a canned picture.
// The server's own rules are covered by backend/tests/test_owner_memory_api.py.

const REFUSE = [
  [/hunter|password|باسورد/i, "sensitive", "الملاحظة دي شكلها سر (باسورد أو كارت أو رقم قومي أو مفتاح)."],
  [/تجاهل كل/, "instruction", "الملاحظة دي شكلها تعليمات للمساعد مش معلومة عنك، ومبتتحفظش."],
];

function memoryApi(page, { max = 50, seed = [] } = {}) {
  const state = { enabled: true, notes: [...seed], calls: [] };
  let n = 100;
  const note = (content) => ({
    id: `00000000-0000-4000-8000-${String(++n).padStart(12, "0")}`,
    content,
    source: "explicit",
    created_at: "2026-11-13T10:00:00Z",
    updated_at: "2026-11-13T10:00:00Z",
  });
  const refusal = (reason, message, status = 422) => ({
    status,
    json: { error: { code: status === 409 ? "memory_unavailable" : "memory_refused", message, retryable: false, details: { reason } } },
  });
  const body = (r) => {
    try { return r.request().postDataJSON() ?? {}; } catch { return {}; }
  };

  return page.route("**/api/v1/**", (r) => {
    const req = r.request();
    const url = new URL(req.url());
    const path = url.pathname.replace("/api/v1", "");
    if (path === "/auth/me") return r.fulfill({ json: { id: "u1", email: "t@e.com", full_name: "T", role: "owner" } });
    if (!path.startsWith("/ai/owner-memory")) return r.fulfill({ json: [] });
    state.calls.push(`${req.method()} ${path}`);

    if (path === "/ai/owner-memory/enabled" && req.method() === "PUT") {
      state.enabled = body(r).enabled;
      return r.fulfill({ json: { enabled: state.enabled } });
    }
    if (path === "/ai/owner-memory" && req.method() === "GET") {
      return r.fulfill({ json: { enabled: state.enabled, notes: [...state.notes].reverse(), max_notes: max, max_chars: 500 } });
    }
    if (path === "/ai/owner-memory" && req.method() === "POST") {
      const text = String(body(r).content ?? "").trim();
      const hit = REFUSE.find(([re]) => re.test(text));
      if (hit) return r.fulfill(refusal(hit[1], hit[2]));
      if (state.notes.length >= max) return r.fulfill(refusal("full", "الذاكرة ممتلئة. امسح ملاحظات قديمة الأول.", 409));
      const created = note(text);
      state.notes.push(created);
      return r.fulfill({ status: 201, json: created });
    }
    if (path === "/ai/owner-memory" && req.method() === "DELETE") {
      const removed = state.notes.length;
      state.notes = [];
      return r.fulfill({ json: { removed } });
    }
    const id = path.split("/").pop();
    const found = state.notes.find((x) => x.id === id);
    if (!found) return r.fulfill({ status: 404, json: { error: { code: "not_found", message: "الملاحظة مش موجودة", retryable: false } } });
    if (req.method() === "PATCH") {
      const text = String(body(r).content ?? "").trim();
      const hit = REFUSE.find(([re]) => re.test(text));
      if (hit) return r.fulfill(refusal(hit[1], hit[2]));
      found.content = text;
      return r.fulfill({ json: found });
    }
    if (req.method() === "DELETE") {
      state.notes = state.notes.filter((x) => x.id !== id);
      return r.fulfill({ status: 204, body: "" });
    }
    return r.fulfill({ status: 405, json: {} });
  }).then(() => state);
}

async function open(page) {
  await page.context().addCookies([{ name: "csrf_token", value: "test", url: "http://127.0.0.1:4173" }]);
  await page.addInitScript(() => localStorage.setItem("salesos.lang", "ar"));
  await page.goto("/sales-assistant", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "ذاكرة المساعد" }).click();
  await expect(page.getByRole("dialog", { name: "اللي المساعد فاكره عنك" })).toBeVisible();
  return page.getByRole("dialog", { name: "اللي المساعد فاكره عنك" });
}

test("with no notes, delete-all is not offered; with notes it is", async ({ page }) => {
  await memoryApi(page);
  const panel = await open(page);
  await expect(panel.getByRole("button", { name: /امسح كل الملاحظات/ })).toHaveCount(0);
  await panel.getByPlaceholder("اكتب حاجة تحب المساعد يفتكرها…").fill("ملاحظة");
  await panel.getByRole("button", { name: "حفظ", exact: true }).click();
  await expect(panel.getByRole("button", { name: /امسح كل الملاحظات/ })).toBeVisible();
});

test("the owner adds a note and sees it, newest first", async ({ page }) => {
  await memoryApi(page);
  const panel = await open(page);
  await expect(panel.getByText("مفيش ملاحظات لسه", { exact: false })).toBeVisible();
  const box = panel.getByPlaceholder("اكتب حاجة تحب المساعد يفتكرها…");
  await box.fill("بحب أشوف الأرقام بالجنيه");
  await panel.getByRole("button", { name: "حفظ", exact: true }).click();
  await expect(panel.getByText("بحب أشوف الأرقام بالجنيه")).toBeVisible();
  await box.fill("بقفل المحل الساعة 11");
  await panel.getByRole("button", { name: "حفظ", exact: true }).click();
  const items = panel.locator("li p");
  await expect(items.first()).toHaveText("بقفل المحل الساعة 11");
  await expect(box).toHaveValue("");
});

test("a refused note shows the server's reason, is not echoed back, and nothing is saved", async ({ page }) => {
  const api = await memoryApi(page);
  const panel = await open(page);
  const box = panel.getByPlaceholder("اكتب حاجة تحب المساعد يفتكرها…");
  await box.fill("الباسورد بتاعي Hunter22xyz");
  await panel.getByRole("button", { name: "حفظ", exact: true }).click();
  const alert = panel.getByRole("alert");
  await expect(alert).toContainText("شكلها سر");
  await expect(alert).not.toContainText("Hunter22xyz");
  expect(api.notes).toHaveLength(0);
  await expect(panel.getByText("Hunter22xyz")).toHaveCount(1); // only still in the box the owner typed into
});

test("editing a note rewrites it in place", async ({ page }) => {
  await memoryApi(page, { seed: [{ id: "00000000-0000-4000-8000-000000000001", content: "قديمة", source: "explicit", created_at: "2026-11-13T10:00:00Z", updated_at: "2026-11-13T10:00:00Z" }] });
  const panel = await open(page);
  await panel.getByRole("button", { name: "تعديل" }).click();
  const edit = panel.locator("textarea").first();
  await edit.fill("جديدة");
  await panel.getByRole("button", { name: "حفظ التعديل" }).click();
  await expect(panel.getByText("جديدة", { exact: true })).toBeVisible();
  await expect(panel.getByText("قديمة")).toHaveCount(0);
});

test("deleting one note removes exactly that one, wherever it sits in the list", async ({ page }) => {
  const mk = (i, c) => ({ id: `00000000-0000-4000-8000-00000000000${i}`, content: c, source: "explicit", created_at: "2026-11-13T10:00:00Z", updated_at: "2026-11-13T10:00:00Z" });
  const api = await memoryApi(page, { seed: [mk(1, "أولى"), mk(2, "وسطى"), mk(3, "ثالثة")] });
  const panel = await open(page);
  await panel.locator("li", { hasText: "وسطى" }).getByRole("button", { name: "حذف" }).click();
  await expect(panel.getByText("وسطى", { exact: true })).toHaveCount(0);
  await expect(panel.getByText("أولى", { exact: true })).toBeVisible();
  await expect(panel.getByText("ثالثة", { exact: true })).toBeVisible();
  expect(api.notes.map((x) => x.content)).toEqual(["أولى", "ثالثة"]);
  expect(api.calls.filter((c) => c.startsWith("DELETE"))).toEqual([`DELETE /ai/owner-memory/${mk(2, "").id}`]);
});

test("delete-all asks first, and cancelling deletes nothing", async ({ page }) => {
  const mk = (i) => ({ id: `00000000-0000-4000-8000-00000000000${i}`, content: `ملاحظة ${i}`, source: "explicit", created_at: "2026-11-13T10:00:00Z", updated_at: "2026-11-13T10:00:00Z" });
  const api = await memoryApi(page, { seed: [mk(1), mk(2)] });
  const panel = await open(page);
  await panel.getByRole("button", { name: /امسح كل الملاحظات/ }).click();
  await expect(panel.getByText("هتتمسح كل ملاحظاتك نهائياً")).toBeVisible();
  await panel.getByRole("button", { name: "إلغاء" }).click();
  expect(api.notes).toHaveLength(2);
  expect(api.calls.some((c) => c.startsWith("DELETE"))).toBe(false);
  await panel.getByRole("button", { name: /امسح كل الملاحظات/ }).click();
  await panel.getByRole("button", { name: "أيوه، امسح" }).click();
  await expect(panel.getByText("مفيش ملاحظات لسه", { exact: false })).toBeVisible();
  expect(api.notes).toHaveLength(0);
});

test("a full memory blocks adding and says why", async ({ page }) => {
  const seed = Array.from({ length: 2 }, (_, i) => ({ id: `00000000-0000-4000-8000-00000000000${i + 1}`, content: `ن${i}`, source: "explicit", created_at: "2026-11-13T10:00:00Z", updated_at: "2026-11-13T10:00:00Z" }));
  await memoryApi(page, { max: 2, seed });
  const panel = await open(page);
  await expect(panel.getByText("الذاكرة ممتلئة", { exact: false })).toBeVisible();
  await expect(panel.getByPlaceholder("اكتب حاجة تحب المساعد يفتكرها…")).toBeDisabled();
  await expect(panel.getByRole("button", { name: "حفظ", exact: true })).toBeDisabled();
});

test("switching memory off is sent to the server and disables adding", async ({ page }) => {
  const api = await memoryApi(page);
  const panel = await open(page);
  // click, not uncheck(): the switch shows the SERVER's state, so it only flips once the server
  // has confirmed. uncheck() would fail by design because it demands an instant change.
  await panel.getByRole("switch").click();
  await expect.poll(() => api.enabled).toBe(false);
  await expect(panel.getByRole("switch")).not.toBeChecked();
  await expect(panel.getByText("الذاكرة مقفولة", { exact: false })).toBeVisible();
  await expect(panel.getByPlaceholder("اكتب حاجة تحب المساعد يفتكرها…")).toBeDisabled();
});

test("an over-long draft cannot be sent", async ({ page }) => {
  const api = await memoryApi(page);
  const panel = await open(page);
  await panel.getByPlaceholder("اكتب حاجة تحب المساعد يفتكرها…").fill("ا".repeat(501));
  await expect(panel.getByRole("button", { name: "حفظ", exact: true })).toBeDisabled();
  await expect(panel.getByText("1 زيادة")).toBeVisible();
  expect(api.calls.filter((c) => c.startsWith("POST"))).toHaveLength(0);
});

test("on a phone the panel is a sheet, and there is only one of it", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await memoryApi(page);
  const panel = await open(page);
  // includeHidden: a second copy hidden with display:none is invisible to a normal role query but
  // still owns its own draft and edit state and its own request.
  await expect(page.getByRole("dialog", { includeHidden: true })).toHaveCount(1);
  await expect(page.locator("aside[role=dialog]")).toHaveCount(1);
  const box = await panel.boundingBox();
  expect(box.width).toBeLessThanOrEqual(390);
  await panel.getByRole("button", { name: "إغلاق" }).click();
  await expect(page.getByRole("dialog", { name: "اللي المساعد فاكره عنك" })).toHaveCount(0);
});
