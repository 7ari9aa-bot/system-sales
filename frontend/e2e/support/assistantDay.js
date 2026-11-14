// A stand-in for the sales-chat API with a LOT of content: many threads (so the thread list has to
// scroll) and a long conversation (so the chat has to scroll). Sends are accepted and echoed.
const THREAD_COUNT = 40;
const MESSAGE_PAIRS = 30;

export const threads = Array.from({ length: THREAD_COUNT }, (_, i) => ({
  id: `00000000-0000-4000-8000-${String(i).padStart(12, "0")}`,
  title: `محادثة رقم ${i + 1}`,
  status: "active",
  context: {},
  created_at: "2026-10-10T10:00:00Z",
  updated_at: "2026-10-10T10:05:00Z",
  last_message_at: "2026-10-10T10:05:00Z",
}));

export const messages = (threadId) =>
  Array.from({ length: MESSAGE_PAIRS * 2 }, (_, i) => {
    const user = i % 2 === 0;
    return {
      id: `m-${i}`, thread_id: threadId, sequence_no: i + 1, role: user ? "user" : "assistant", status: "completed",
      content: user ? `سؤال رقم ${i / 2 + 1} عن المبيعات` : `إجابة رقم ${(i + 1) / 2}: الإيراد المسلَّم ارتفع مقارنة بالشهر الماضي بنسبة ملحوظة.`,
      structured_content: null, run_id: null, analysis_id: null, error_code: null,
      created_at: "2026-10-10T10:04:00Z",
    };
  });

/** Mount the mocked day. `sent` collects the bodies of the messages the page posts. */
export async function mockAssistantDay(page, { lang = "ar", empty = false } = {}) {
  const sent = [];
  await page.context().addCookies([{ name: "csrf_token", value: "ui-test", url: "http://127.0.0.1:4173" }]);
  await page.addInitScript((l) => localStorage.setItem("salesos.lang", l), lang);
  await page.route("**/api/v1/**", (r) => {
    const req = r.request();
    const u = new URL(req.url());
    const p = u.pathname.replace("/api/v1", "");
    if (p === "/auth/me") return r.fulfill({ json: { id: "u", email: "ui@example.com", full_name: "Merchant", is_active: true, tenants: [{ id: "tenant", name: "Shop", role_code: "owner" }] } });
    if (p === "/ai/sales-chat/threads" && req.method() === "GET") return r.fulfill({ json: empty ? [] : threads });
    if (p === "/ai/sales-chat/threads" && req.method() === "POST") return r.fulfill({ json: threads[0] });
    const m = p.match(/^\/ai\/sales-chat\/threads\/([^/]+)\/messages$/);
    if (m && req.method() === "GET") return r.fulfill({ json: messages(m[1]) });
    if (m && req.method() === "POST") { sent.push(req.postDataJSON()); return r.fulfill({ json: { ok: true } }); }
    if (p.startsWith("/ai/owner-memory")) return r.fulfill({ json: p.endsWith("suggestions") ? [] : { enabled: true, notes: [], limit: 50 } });
    return r.fulfill({ json: [] });
  });
  return { sent };
}
