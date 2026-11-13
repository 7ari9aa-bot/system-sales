import { expect, test } from "@playwright/test";

// The assistant's memory screen against a STATEFUL stand-in for the API: it keeps the notes, refuses
// what the real server refuses, and answers with the real error shape, so what is checked here is the
// screen's behaviour (add, refusal, edit, delete one, delete all, switch off), not a canned picture.
// The server's own rules are covered by backend/tests/test_owner_memory_api.py.

const REFUSE = [
  [
    /hunter|password|باسورد/i,
    "sensitive",
    "الملاحظة دي شكلها سر (باسورد أو كارت أو رقم قومي أو مفتاح).",
  ],
  [
    /تجاهل كل/,
    "instruction",
    "الملاحظة دي شكلها تعليمات للمساعد مش معلومة عنك، ومبتتحفظش.",
  ],
];

// The fixed sentence per period, exactly as the server owns it. The screen sends only the KEY.
const SENTENCE = {
  last_7_days: "بتفضّل تشوف الأرقام عن آخر 7 أيام",
  this_month: "بتفضّل تشوف الأرقام عن الشهر الحالي",
};

function memoryApi(
  page,
  {
    max = 50,
    seed = [],
    habit = null,
    rawSuggestions = null,
    acceptDelayMs = 0,
  } = {},
) {
  const state = {
    enabled: true,
    notes: [...seed],
    calls: [],
    bodies: [],
    habit,
    dismissed: [],
  };
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
    json: {
      error: {
        code: status === 409 ? "memory_unavailable" : "memory_refused",
        message,
        retryable: false,
        details: { reason },
      },
    },
  });
  const body = (r) => {
    try {
      return r.request().postDataJSON() ?? {};
    } catch {
      return {};
    }
  };

  return page
    .route("**/api/v1/**", (r) => {
      const req = r.request();
      const url = new URL(req.url());
      const path = url.pathname.replace("/api/v1", "");
      if (path === "/auth/me")
        return r.fulfill({
          json: { id: "u1", email: "t@e.com", full_name: "T", role: "owner" },
        });
      if (!path.startsWith("/ai/owner-memory")) return r.fulfill({ json: [] });
      state.calls.push(`${req.method()} ${path}`);
      if (req.method() !== "GET") state.bodies.push({ path, body: body(r) });

      if (
        path === "/ai/owner-memory/suggestions" &&
        req.method() === "GET" &&
        rawSuggestions
      ) {
        return r.fulfill({ json: { suggestions: rawSuggestions } });
      }
      if (path === "/ai/owner-memory/suggestions" && req.method() === "GET") {
        const live =
          state.enabled &&
          state.habit &&
          !state.dismissed.includes(state.habit.period) &&
          !state.notes.some((x) => x.content === SENTENCE[state.habit.period]);
        return r.fulfill({
          json: {
            suggestions: live
              ? [
                  {
                    period: state.habit.period,
                    text: SENTENCE[state.habit.period],
                    count: state.habit.count,
                  },
                ]
              : [],
          },
        });
      }
      if (
        path === "/ai/owner-memory/suggestions/accept" &&
        req.method() === "POST" &&
        acceptDelayMs
      ) {
        return new Promise((resolve) =>
          setTimeout(resolve, acceptDelayMs),
        ).then(() => {
          const created = {
            ...note(SENTENCE[state.habit.period]),
            source: "inferred",
          };
          state.notes.push(created);
          return r.fulfill({ status: 201, json: created });
        });
      }
      if (
        path === "/ai/owner-memory/suggestions/accept" &&
        req.method() === "POST"
      ) {
        if (!state.enabled)
          return r.fulfill(
            refusal("disabled", "الذاكرة مقفولة. شغّلها الأول.", 409),
          );
        if (!state.habit || body(r).period !== state.habit.period)
          return r.fulfill({
            status: 404,
            json: {
              error: {
                code: "not_found",
                message: "الاقتراح ده مش موجود",
                retryable: false,
              },
            },
          });
        if (state.notes.length >= max)
          return r.fulfill(
            refusal("full", "الذاكرة ممتلئة. امسح ملاحظات قديمة الأول.", 409),
          );
        // the server saves ITS sentence, whatever else the request carried
        const created = {
          ...note(SENTENCE[state.habit.period]),
          source: "inferred",
        };
        state.notes.push(created);
        return r.fulfill({ status: 201, json: created });
      }
      if (
        path === "/ai/owner-memory/suggestions/dismiss" &&
        req.method() === "POST"
      ) {
        state.dismissed.push(body(r).period);
        return r.fulfill({ status: 204, body: "" });
      }

      if (path === "/ai/owner-memory/enabled" && req.method() === "PUT") {
        state.enabled = body(r).enabled;
        return r.fulfill({ json: { enabled: state.enabled } });
      }
      if (path === "/ai/owner-memory" && req.method() === "GET") {
        return r.fulfill({
          json: {
            enabled: state.enabled,
            notes: [...state.notes].reverse(),
            max_notes: max,
            max_chars: 500,
          },
        });
      }
      if (path === "/ai/owner-memory" && req.method() === "POST") {
        const text = String(body(r).content ?? "").trim();
        const hit = REFUSE.find(([re]) => re.test(text));
        if (hit) return r.fulfill(refusal(hit[1], hit[2]));
        if (state.notes.length >= max)
          return r.fulfill(
            refusal("full", "الذاكرة ممتلئة. امسح ملاحظات قديمة الأول.", 409),
          );
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
      if (!found)
        return r.fulfill({
          status: 404,
          json: {
            error: {
              code: "not_found",
              message: "الملاحظة مش موجودة",
              retryable: false,
            },
          },
        });
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
    })
    .then(() => state);
}

async function open(page) {
  await page
    .context()
    .addCookies([
      { name: "csrf_token", value: "test", url: "http://127.0.0.1:4173" },
    ]);
  await page.addInitScript(() => localStorage.setItem("salesos.lang", "ar"));
  await page.goto("/sales-assistant", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "ذاكرة المساعد" }).click();
  await expect(
    page.getByRole("dialog", { name: "اللي المساعد فاكره عنك" }),
  ).toBeVisible();
  return page.getByRole("dialog", { name: "اللي المساعد فاكره عنك" });
}

test("with no notes, delete-all is not offered; with notes it is", async ({
  page,
}) => {
  await memoryApi(page);
  const panel = await open(page);
  await expect(
    panel.getByRole("button", { name: /امسح كل الملاحظات/ }),
  ).toHaveCount(0);
  await panel.getByPlaceholder("اكتب حاجة تحب المساعد يفتكرها…").fill("ملاحظة");
  await panel.getByRole("button", { name: "حفظ", exact: true }).click();
  await expect(
    panel.getByRole("button", { name: /امسح كل الملاحظات/ }),
  ).toBeVisible();
});

test("the owner adds a note and sees it, newest first", async ({ page }) => {
  await memoryApi(page);
  const panel = await open(page);
  await expect(
    panel.getByText("مفيش ملاحظات لسه", { exact: false }),
  ).toBeVisible();
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

test("a refused note shows the server's reason, is not echoed back, and nothing is saved", async ({
  page,
}) => {
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
  await memoryApi(page, {
    seed: [
      {
        id: "00000000-0000-4000-8000-000000000001",
        content: "قديمة",
        source: "explicit",
        created_at: "2026-11-13T10:00:00Z",
        updated_at: "2026-11-13T10:00:00Z",
      },
    ],
  });
  const panel = await open(page);
  await panel.getByRole("button", { name: "تعديل" }).click();
  const edit = panel.locator("textarea").first();
  await edit.fill("جديدة");
  await panel.getByRole("button", { name: "حفظ التعديل" }).click();
  await expect(panel.getByText("جديدة", { exact: true })).toBeVisible();
  await expect(panel.getByText("قديمة")).toHaveCount(0);
});

test("deleting one note removes exactly that one, wherever it sits in the list", async ({
  page,
}) => {
  const mk = (i, c) => ({
    id: `00000000-0000-4000-8000-00000000000${i}`,
    content: c,
    source: "explicit",
    created_at: "2026-11-13T10:00:00Z",
    updated_at: "2026-11-13T10:00:00Z",
  });
  const api = await memoryApi(page, {
    seed: [mk(1, "أولى"), mk(2, "وسطى"), mk(3, "ثالثة")],
  });
  const panel = await open(page);
  await panel
    .locator("li", { hasText: "وسطى" })
    .getByRole("button", { name: "حذف" })
    .click();
  await expect(panel.getByText("وسطى", { exact: true })).toHaveCount(0);
  await expect(panel.getByText("أولى", { exact: true })).toBeVisible();
  await expect(panel.getByText("ثالثة", { exact: true })).toBeVisible();
  expect(api.notes.map((x) => x.content)).toEqual(["أولى", "ثالثة"]);
  expect(api.calls.filter((c) => c.startsWith("DELETE"))).toEqual([
    `DELETE /ai/owner-memory/${mk(2, "").id}`,
  ]);
});

test("delete-all asks first, and cancelling deletes nothing", async ({
  page,
}) => {
  const mk = (i) => ({
    id: `00000000-0000-4000-8000-00000000000${i}`,
    content: `ملاحظة ${i}`,
    source: "explicit",
    created_at: "2026-11-13T10:00:00Z",
    updated_at: "2026-11-13T10:00:00Z",
  });
  const api = await memoryApi(page, { seed: [mk(1), mk(2)] });
  const panel = await open(page);
  await panel.getByRole("button", { name: /امسح كل الملاحظات/ }).click();
  await expect(panel.getByText("هتتمسح كل ملاحظاتك نهائياً")).toBeVisible();
  await panel.getByRole("button", { name: "إلغاء" }).click();
  expect(api.notes).toHaveLength(2);
  expect(api.calls.some((c) => c.startsWith("DELETE"))).toBe(false);
  await panel.getByRole("button", { name: /امسح كل الملاحظات/ }).click();
  await panel.getByRole("button", { name: "أيوه، امسح" }).click();
  await expect(
    panel.getByText("مفيش ملاحظات لسه", { exact: false }),
  ).toBeVisible();
  expect(api.notes).toHaveLength(0);
});

test("a full memory blocks adding and says why", async ({ page }) => {
  const seed = Array.from({ length: 2 }, (_, i) => ({
    id: `00000000-0000-4000-8000-00000000000${i + 1}`,
    content: `ن${i}`,
    source: "explicit",
    created_at: "2026-11-13T10:00:00Z",
    updated_at: "2026-11-13T10:00:00Z",
  }));
  await memoryApi(page, { max: 2, seed });
  const panel = await open(page);
  await expect(
    panel.getByText("الذاكرة ممتلئة", { exact: false }),
  ).toBeVisible();
  await expect(
    panel.getByPlaceholder("اكتب حاجة تحب المساعد يفتكرها…"),
  ).toBeDisabled();
  await expect(
    panel.getByRole("button", { name: "حفظ", exact: true }),
  ).toBeDisabled();
});

test("switching memory off is sent to the server and disables adding", async ({
  page,
}) => {
  const api = await memoryApi(page);
  const panel = await open(page);
  // click, not uncheck(): the switch shows the SERVER's state, so it only flips once the server
  // has confirmed. uncheck() would fail by design because it demands an instant change.
  await panel.getByRole("switch").click();
  await expect.poll(() => api.enabled).toBe(false);
  await expect(panel.getByRole("switch")).not.toBeChecked();
  await expect(
    panel.getByText("الذاكرة مقفولة", { exact: false }),
  ).toBeVisible();
  await expect(
    panel.getByPlaceholder("اكتب حاجة تحب المساعد يفتكرها…"),
  ).toBeDisabled();
});

test("an over-long draft cannot be sent", async ({ page }) => {
  const api = await memoryApi(page);
  const panel = await open(page);
  await panel
    .getByPlaceholder("اكتب حاجة تحب المساعد يفتكرها…")
    .fill("ا".repeat(501));
  await expect(
    panel.getByRole("button", { name: "حفظ", exact: true }),
  ).toBeDisabled();
  await expect(panel.getByText("1 زيادة")).toBeVisible();
  expect(api.calls.filter((c) => c.startsWith("POST"))).toHaveLength(0);
});

test("on a phone the panel is a sheet, and there is only one of it", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await memoryApi(page);
  const panel = await open(page);
  // includeHidden: a second copy hidden with display:none is invisible to a normal role query but
  // still owns its own draft and edit state and its own request.
  await expect(page.getByRole("dialog", { includeHidden: true })).toHaveCount(
    1,
  );
  await expect(page.locator("aside[role=dialog]")).toHaveCount(1);
  const box = await panel.boundingBox();
  expect(box.width).toBeLessThanOrEqual(390);
  await panel.getByRole("button", { name: "إغلاق" }).click();
  await expect(
    page.getByRole("dialog", { name: "اللي المساعد فاكره عنك" }),
  ).toHaveCount(0);
});

test("a habit is offered with how often it was seen, and nothing is saved until the owner agrees", async ({
  page,
}) => {
  const api = await memoryApi(page, {
    habit: { period: "last_7_days", count: 8 },
  });
  const panel = await open(page);
  const offer = panel.getByTestId("habit-suggestion");
  await expect(offer).toHaveCount(1);
  await expect(offer).toContainText("بتفضّل تشوف الأرقام عن آخر 7 أيام");
  await expect(offer).toContainText("8");
  await expect(offer).toContainText("مش هحفظها إلا لو وافقت");
  expect(api.notes).toHaveLength(0);
  expect(api.calls.filter((c) => c.startsWith("POST"))).toEqual([]);
});

test("accepting sends only the period key, and the note then shows as inferred", async ({
  page,
}) => {
  const api = await memoryApi(page, {
    habit: { period: "last_7_days", count: 8 },
  });
  const panel = await open(page);
  await panel.getByRole("button", { name: "احفظها" }).click();
  await expect(panel.getByTestId("habit-suggestion")).toHaveCount(0);
  await expect(panel.getByText("استنتجتها من كلامك")).toBeVisible();
  const sent = api.bodies.find((b) => b.path.endsWith("/accept"));
  expect(sent.body).toEqual({ period: "last_7_days" }); // no text field, ever
  expect(api.notes.map((n) => n.content)).toEqual([
    "بتفضّل تشوف الأرقام عن آخر 7 أيام",
  ]);
});

test("dismissing hides it, saves nothing, and it stays hidden after a reload", async ({
  page,
}) => {
  const api = await memoryApi(page, {
    habit: { period: "last_7_days", count: 8 },
  });
  const panel = await open(page);
  await panel.getByRole("button", { name: "لا، شكراً" }).click();
  await expect(panel.getByTestId("habit-suggestion")).toHaveCount(0);
  expect(api.notes).toHaveLength(0);
  expect(api.dismissed).toEqual(["last_7_days"]);
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "ذاكرة المساعد" }).click();
  await expect(
    page.getByRole("dialog", { name: "اللي المساعد فاكره عنك" }),
  ).toBeVisible();
  await expect(page.getByTestId("habit-suggestion")).toHaveCount(0);
});

test("no habit means no suggestion block at all", async ({ page }) => {
  await memoryApi(page);
  const panel = await open(page);
  await expect(panel.getByTestId("habit-suggestion")).toHaveCount(0);
  await expect(panel.getByText("لاحظت حاجة")).toHaveCount(0);
});

test("with memory off nothing is suggested, and it comes back when memory is switched on", async ({
  page,
}) => {
  const api = await memoryApi(page, {
    habit: { period: "last_7_days", count: 8 },
  });
  const panel = await open(page);
  await expect(panel.getByTestId("habit-suggestion")).toHaveCount(1);
  await panel.getByRole("switch").click();
  await expect.poll(() => api.enabled).toBe(false);
  await expect(panel.getByTestId("habit-suggestion")).toHaveCount(0);
  await panel.getByRole("switch").click();
  await expect.poll(() => api.enabled).toBe(true);
  await expect(panel.getByTestId("habit-suggestion")).toHaveCount(1);
});

test("a full memory does not offer a suggestion it could not save", async ({
  page,
}) => {
  const mk = (i) => ({
    id: `00000000-0000-4000-8000-0000000000${String(i).padStart(2, "0")}`,
    content: `ملاحظة ${i}`,
    source: "explicit",
    created_at: "2026-11-13T10:00:00Z",
    updated_at: "2026-11-13T10:00:00Z",
  });
  await memoryApi(page, {
    max: 2,
    seed: [mk(1), mk(2)],
    habit: { period: "last_7_days", count: 8 },
  });
  const panel = await open(page);
  await expect(panel.getByText("اللي المساعد فاكره عنك")).toBeVisible();
  await expect(panel.getByTestId("habit-suggestion")).toHaveCount(0);
});

test("a refused acceptance shows the server's reason and keeps the suggestion", async ({
  page,
}) => {
  const api = await memoryApi(page, {
    habit: { period: "last_7_days", count: 8 },
  });
  const panel = await open(page);
  api.habit = { period: "this_month", count: 8 }; // the habit moved on after the screen loaded
  await panel.getByRole("button", { name: "احفظها" }).click();
  await expect(panel.getByRole("alert")).toContainText("الاقتراح ده مش موجود");
  expect(api.notes).toHaveLength(0);
});

test("a suggestion does not crowd out the phone layout", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 780 });
  await memoryApi(page, { habit: { period: "last_7_days", count: 8 } });
  const panel = await open(page);
  const offer = panel.getByTestId("habit-suggestion");
  await expect(offer).toBeVisible();
  const box = await panel.boundingBox();
  const buttons = await offer
    .getByRole("button")
    .evaluateAll((els) => els.map((e) => e.getBoundingClientRect()));
  for (const b of buttons) {
    expect(b.left).toBeGreaterThanOrEqual(box.x - 1);
    expect(b.right).toBeLessThanOrEqual(box.x + box.width + 1);
  }
});

test("a suggestion for a period the server cannot accept, or with no text, is never shown", async ({
  page,
}) => {
  await memoryApi(page, {
    rawSuggestions: [
      { period: "../etc", text: "بتفضّل حاجة غريبة", count: 9 },
      { period: "today", text: "   ", count: 9 },
      { period: "yesterday", count: 9 },
    ],
  });
  const panel = await open(page);
  await expect(panel.getByText("اللي المساعد فاكره عنك")).toBeVisible();
  await expect(panel.getByTestId("habit-suggestion")).toHaveCount(0);
  await expect(panel.getByText("بتفضّل حاجة غريبة")).toHaveCount(0);
});

test("while a suggestion is being saved both of its buttons are locked", async ({
  page,
}) => {
  await memoryApi(page, {
    habit: { period: "last_7_days", count: 8 },
    acceptDelayMs: 4000,
  });
  const panel = await open(page);
  await panel.getByRole("button", { name: "احفظها" }).click();
  await expect(panel.getByRole("button", { name: "احفظها" })).toBeDisabled();
  await expect(panel.getByRole("button", { name: "لا، شكراً" })).toBeDisabled();
  await expect(panel.getByTestId("habit-suggestion")).toHaveCount(0);
});

test("a suggestion already loaded is hidden the moment memory is switched off", async ({
  page,
}) => {
  // The stand-in keeps answering with the suggestion after the switch (a stale list, or a second
  // device): the screen itself must not keep offering it.
  await memoryApi(page, {
    rawSuggestions: [
      {
        period: "last_7_days",
        text: "بتفضّل تشوف الأرقام عن آخر 7 أيام",
        count: 8,
      },
    ],
  });
  const panel = await open(page);
  await expect(panel.getByTestId("habit-suggestion")).toHaveCount(1);
  await panel.getByRole("switch").click();
  await expect(panel.getByRole("switch")).not.toBeChecked();
  await expect(panel.getByTestId("habit-suggestion")).toHaveCount(0);
});
