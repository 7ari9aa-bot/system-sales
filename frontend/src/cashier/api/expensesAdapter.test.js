import { describe, expect, it } from "vitest";
import {
  buildExpense,
  buildVoid,
  categoriesFromApi,
  expenseErrorMessage,
  expenseFromApi,
  expensesFromApi,
  filterExpenses,
  normalizeAmountInput,
  summarize,
} from "./expensesAdapter";

const CATS = [
  { id: "c1", name: "كهرباء ومياه" },
  { id: "c2", name: "إيجار" },
];
const api = (o = {}) => ({
  id: "e1", number: "EXP-2026-0001", category_id: "c1", description: "فاتورة", amount: "100.00",
  payment_method: "cash", expense_date: "2026-10-20", session_id: "s1", status: "posted",
  void_reason: null, created_at: "2026-10-20T10:00:00Z", created_by_user_id: "u1", ...o,
});
const rows = (list) => expensesFromApi(list, { categories: CATS, users: { u1: "منى" } });

describe("amount input", () => {
  it.each([
    ["45", "45.00"], ["45.5", "45.50"], ["45.50", "45.50"], [" 7.25 ", "7.25"],
    ["٤٥٫٥", "45.50"], ["١٢٣", "123.00"], ["45,5", "45.50"], ["۱۲٫۵", "12.50"],
  ])("%s -> %s", (raw, out) => expect(normalizeAmountInput(raw)).toBe(out));

  it.each([["0"], ["0.00"], ["-5"], ["abc"], [""], ["   "], ["10.005"], ["1e3"], ["1.2.3"], [null], [undefined], ["NaN"]])(
    "%j is refused (never rounded, never guessed)",
    (raw) => expect(normalizeAmountInput(raw)).toBeNull(),
  );
});

describe("buildExpense", () => {
  const ok = { categoryId: "c1", description: " كهرباء ", amount: "50", payment: "card", date: "2026-10-20" };
  it("builds the wire payload, trimmed, with no shift for a non-cash expense", () => {
    const r = buildExpense(ok);
    expect(r).toEqual({
      ok: true,
      payload: { category_id: "c1", description: "كهرباء", amount: "50.00", payment_method: "card", expense_date: "2026-10-20" },
    });
    expect("session_id" in r.payload).toBe(false);
  });
  it("a CASH expense is tied to the open shift", () => {
    expect(buildExpense({ ...ok, payment: "cash" }, { openSessionId: "s9" }).payload.session_id).toBe("s9");
  });
  it("a CASH expense with no open shift is accepted: it is a record, and it carries no shift", () => {
    const r = buildExpense({ ...ok, payment: "cash" }, { openSessionId: null });
    expect(r.ok).toBe(true);
    expect("session_id" in r.payload).toBe(false);
    expect(r.payload.payment_method).toBe("cash");
  });
  it("a non-cash expense never carries a shift even if one is open", () => {
    expect("session_id" in buildExpense(ok, { openSessionId: "s9" }).payload).toBe(false);
  });
  it.each([
    [{ categoryId: "" }, /التصنيف/], [{ description: "   " }, /بيان/], [{ amount: "0" }, /المبلغ/],
    [{ amount: "10.005" }, /المبلغ/], [{ payment: "crypto" }, /طريقة الدفع/], [{ date: "" }, /تاريخ/], [{ date: "20/10/2026" }, /تاريخ/],
    [{ description: "x".repeat(256) }, /أطول/],
  ])("refuses %j", (patch, msg) => {
    const r = buildExpense({ ...ok, ...patch });
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(msg);
  });
});

describe("buildVoid", () => {
  it("needs a reason", () => {
    expect(buildVoid("  ").ok).toBe(false);
    expect(buildVoid(undefined).ok).toBe(false);
    expect(buildVoid(" اتسجل بالغلط ")).toEqual({ ok: true, payload: { reason: "اتسجل بالغلط" } });
    expect(buildVoid("x".repeat(256)).ok).toBe(false);
  });
});

describe("mapping", () => {
  it("keeps the amount as the backend's exact text and resolves names", () => {
    const [r] = rows([api()]);
    expect(r).toMatchObject({ amount: "100.00", category: "كهرباء ومياه", employee: "منى", voided: false, payment: "cash" });
  });
  it("unknown category or user degrade to a dash, never crash", () => {
    const [r] = rows([api({ category_id: "zzz", created_by_user_id: null })]);
    expect(r.category).toBe("—");
    expect(r.employee).toBe("—");
  });
  it("accepts the {items,totals} payload or a bare list", () => {
    expect(rows({ items: [api()], totals: {} })).toHaveLength(1);
    expect(rows([api(), api({ id: "e2" })])).toHaveLength(2);
    expect(rows(null)).toEqual([]);
  });
  it("hides inactive categories", () => {
    expect(categoriesFromApi([{ id: "a", name: "x", is_active: true }, { id: "b", name: "y", is_active: false }])).toEqual([{ id: "a", name: "x" }]);
    expect(categoriesFromApi(undefined)).toEqual([]);
  });
  it("a voided row says so and keeps its reason", () => {
    const [r] = rows([api({ status: "voided", void_reason: "غلط" })]);
    expect(r).toMatchObject({ voided: true, voidReason: "غلط" });
  });
});

describe("summarize: money is exact and a voided expense is never counted", () => {
  const list = rows([
    api({ id: "1", amount: "0.10", category_id: "c1" }),
    api({ id: "2", amount: "0.20", category_id: "c1", payment_method: "card", session_id: null }),
    api({ id: "3", amount: "500.00", category_id: "c2", payment_method: "bank_transfer", session_id: null, expense_date: "2026-10-01" }),
    api({ id: "4", amount: "9999.00", category_id: "c2", status: "voided" }),
  ]);
  const s = summarize(list, { today: "2026-10-20" });
  it("0.1 + 0.2 is 0.30 (no float drift)", () => expect(summarize(rows([api({ amount: "0.10" }), api({ id: "x", amount: "0.20" })])).total).toBe("0.30"));
  it("totals ignore the voided one", () => expect(s).toMatchObject({ total: "500.30", count: 3, voidedCount: 1 }));
  it("today / cash / top category", () => {
    expect(s.today).toBe("0.30");
    expect(s.cash).toBe("0.10");
    expect(s.top).toBe("إيجار");
    expect(s.topAmount).toBe("500.00");
  });
  it("empty list is zero, not NaN", () => expect(summarize([])).toMatchObject({ total: "0.00", count: 0, top: "—", topAmount: "0.00" }));
});

describe("summarize uses the shop's day by default", () => {
  it("an expense dated today counts as today even right after Cairo midnight", () => {
    const row = rows([api({ id: "z", amount: "7.00", expense_date: "2026-01-21" })]);
    // 22:30Z on the 20th is 00:30 on the 21st in Cairo: it must count as TODAY.
    const realNow = Date.now;
    Date.now = () => new Date("2026-01-20T22:30:00Z").getTime();
    const OriginalDate = Date;
    globalThis.Date = class extends OriginalDate {
      constructor(...a) { super(...(a.length ? a : [Date.now()])); }
    };
    try {
      expect(summarize(row).today).toBe("7.00");
    } finally {
      globalThis.Date = OriginalDate;
      Date.now = realNow;
    }
  });
});

describe("filterExpenses", () => {
  const list = rows([
    api({ id: "1", description: "فاتورة الكهرباء" }),
    api({ id: "2", number: "EXP-2026-0002", description: "ايجار الشهر", category_id: "c2", payment_method: "bank_transfer", session_id: null }),
    api({ id: "3", status: "voided", description: "ملغي" }),
  ]);
  it("searches number / description / category / employee", () => {
    expect(filterExpenses(list, { term: "0002" })).toHaveLength(1);
    expect(filterExpenses(list, { term: "كهرباء" }).map((r) => r.id)).toEqual(["1", "3"]);
    expect(filterExpenses(list, { term: "منى" })).toHaveLength(3);
  });
  it("filters by category and payment, and can hide voided", () => {
    expect(filterExpenses(list, { category: "إيجار" })).toHaveLength(1);
    expect(filterExpenses(list, { payment: "bank_transfer" })).toHaveLength(1);
    expect(filterExpenses(list, { showVoided: false })).toHaveLength(2);
  });
});

describe("expenseErrorMessage", () => {
  it.each([
    [{ status: 409, detail: "this expense is already voided" }, /اتلغى/],
    [{ status: 409, detail: "the shift that paid this expense is closed: record the correction" }, /اتقفلت/],
    [{ status: 409, detail: "a cash expense is paid from an open shift: open a shift first" }, /وردية/],
    [{ status: 403, detail: "forbidden" }, /صلاحية/],
    [{ status: 404, detail: "expense not found" }, /مش موجود/],
    [{ status: 0, message: "network" }, /الاتصال/],
    [{ status: 503, message: "x" }, /الاتصال/],
  ])("%j", (err, re) => expect(expenseErrorMessage(err)).toMatch(re));
  it("unknown errors keep their own text; empty gets a fallback", () => {
    expect(expenseErrorMessage({ status: 400, message: "شيء غريب" })).toBe("شيء غريب");
    expect(expenseErrorMessage({})).toBe("حصل خطأ غير متوقع");
  });
});

describe("expenseFromApi", () => {
  it("is total over a minimal row", () => {
    expect(() => expenseFromApi({ id: 1, number: "n", amount: "1.00", payment_method: "cash", expense_date: "2026-01-01" })).not.toThrow();
  });
});
