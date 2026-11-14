// A stand-in for the sales-chat API with a LOT of content: many threads (so the thread list has to
// scroll) and a long conversation (so the chat has to scroll). Sends are accepted and echoed.
const THREAD_COUNT = 40;
const MESSAGE_PAIRS = 30;

// what the model is asked to write: at most 48 characters, so two lines hold it whole
export const LONG_TITLE = "مقارنة مبيعات الشهر الحالي بالشهر اللي فات";
// an older title cut by hand at 60 characters: it may need the ellipsis
export const OLD_TITLE = "قارنلي مبيعات الشهر ده بالشهر اللي فات وقولي أنهي منتجات اتأثرت";
export const threads = Array.from({ length: THREAD_COUNT }, (_, i) => ({
  id: `00000000-0000-4000-8000-${String(i).padStart(12, "0")}`,
  title: i === 1 ? LONG_TITLE : i === 2 ? OLD_TITLE : `محادثة رقم ${i + 1}`,
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
export async function mockAssistantDay(page, { lang = "ar", empty = false, sendStatus = 200, sendDelayMs = 0, createStatus = 200 } = {}) {
  const sent = [];
  const state = { sendStatus, sendDelayMs, createStatus, custom: null };
  await page.context().addCookies([{ name: "csrf_token", value: "ui-test", url: "http://127.0.0.1:4173" }]);
  await page.addInitScript((l) => localStorage.setItem("salesos.lang", l), lang);
  await page.route("**/api/v1/**", (r) => {
    const req = r.request();
    const u = new URL(req.url());
    const p = u.pathname.replace("/api/v1", "");
    if (p === "/auth/me") return r.fulfill({ json: { id: "u", email: "ui@example.com", full_name: "Merchant", is_active: true, tenants: [{ id: "tenant", name: "Shop", role_code: "owner" }] } });
    if (p === "/ai/sales-chat/threads" && req.method() === "GET") return r.fulfill({ json: empty ? [] : threads });
    if (p === "/ai/sales-chat/threads" && req.method() === "POST") return state.createStatus === 200 ? r.fulfill({ json: threads[0] }) : r.fulfill({ status: state.createStatus, json: { detail: "boom" } });
    const m = p.match(/^\/ai\/sales-chat\/threads\/([^/]+)\/messages$/);
    // The real API lists NEWEST FIRST (it pages backwards); the page has to put them in order.
    if (m && req.method() === "GET") return r.fulfill({ json: state.custom ? [...state.custom] : [...messages(m[1])].reverse() });
    if (m && req.method() === "POST") {
      sent.push(req.postDataJSON());
      const reply = () => (state.sendStatus === 200 ? r.fulfill({ json: { ok: true } }) : r.fulfill({ status: state.sendStatus, json: { detail: "boom" } }));
      return state.sendDelayMs ? setTimeout(reply, state.sendDelayMs) : reply();
    }
    if (p.startsWith("/ai/owner-memory")) return r.fulfill({ json: p.endsWith("suggestions") ? [] : { enabled: true, notes: [], limit: 50 } });
    return r.fulfill({ json: [] });
  });
  return { sent, state };
}

/** One real exchange as production stores it: the answer text appears in `content` AND as a text
 *  block, followed by a refs block with the run id. Newest first, as the API returns it. */
export const realExchange = (answer, question = "هلا") => [
  {
    id: "m-2", thread_id: "t", sequence_no: 2, role: "assistant", status: "completed", content: answer,
    structured_content: [{ type: "text", body: answer }, { type: "refs", run_id: "c26f61a9-48b7-474c-9c6d-82b5f75fb318", analysis_id: null }],
    run_id: "c26f61a9-48b7-474c-9c6d-82b5f75fb318", analysis_id: null, error_code: null, created_at: "2026-11-14T16:05:35Z",
  },
  {
    id: "m-1", thread_id: "t", sequence_no: 1, role: "user", status: "completed", content: question,
    structured_content: null, run_id: null, analysis_id: null, error_code: null, created_at: "2026-11-14T16:05:35Z",
  },
];
