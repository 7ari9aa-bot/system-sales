import { describe, expect, it } from "vitest";
import {
  addLine,
  buildPayment,
  buildPurchaseOrder,
  buildReturn,
  filterOrders,
  linesTotal,
  lineTotal,
  orderFromApi,
  parseCost,
  parsePayment,
  parseQuantity,
  piecesOf,
  purchasesSummary,
  purchasingErrorMessage,
  returnFromApi,
  returnsSummary,
  supplierFromApi,
  suppliersSummary,
} from "./purchasingAdapter";

const V1 = "11111111-1111-1111-1111-111111111111";
const V2 = "22222222-2222-2222-2222-222222222222";

describe("quantity: whole numbers only", () => {
  it.each([["3", 3], [" 12 ", 12], ["4.0", 4], ["٧", 7], ["۱۲", 12], [5, 5]])("%j -> %j", (raw, out) =>
    expect(parseQuantity(raw)).toBe(out),
  );
  it.each([["0"], ["-1"], ["2.5"], ["1e3"], ["abc"], [""], [null], [undefined], ["1,000"], ["1000001"], ["NaN"], ["0x10"]])(
    "%j is refused (never read as something else)",
    (raw) => expect(parseQuantity(raw)).toBeNull(),
  );
});

describe("cost vs payment: zero is a valid cost, never a valid payment", () => {
  it.each([["0", "0.00"], ["12.5", "12.50"], ["٤٥٫٥", "45.50"], ["7,25", "7.25"], ["100", "100.00"]])("cost %j -> %j", (raw, out) =>
    expect(parseCost(raw)).toBe(out),
  );
  it.each([["10.005"], ["-1"], ["abc"], [""], [null], ["1e3"]])("cost %j is refused", (raw) => expect(parseCost(raw)).toBeNull());
  it("a payment of zero is refused", () => {
    expect(parsePayment("0")).toBeNull();
    expect(parsePayment("0.00")).toBeNull();
    expect(parsePayment("0.01")).toBe("0.01");
  });
});

describe("money maths is exact", () => {
  it("line totals use integer cents", () => {
    expect(lineTotal(3, "12.50")).toBe("37.50");
    expect(lineTotal(3, "0.10")).toBe("0.30"); // float would give 0.30000000000000004
    expect(lineTotal(7, "19.99")).toBe("139.93");
  });
  it("the order total is the exact sum", () => {
    let lines = [];
    for (const [v, q, c] of [[V1, 3, "0.10"], [V2, 3, "0.20"]]) lines = addLine(lines, { variantId: v, label: v, qty: q, unitCost: c }).lines;
    expect(linesTotal(lines)).toBe("0.90");
    expect(piecesOf(lines)).toBe(6);
  });
});

describe("addLine", () => {
  const ok = { variantId: V1, label: "تيشيرت", qty: "2", unitCost: "50" };
  it("adds a line with an exact total", () => {
    const r = addLine([], ok);
    expect(r.ok).toBe(true);
    expect(r.lines).toEqual([{ variantId: V1, label: "تيشيرت", qty: 2, unitCost: "50.00", total: "100.00" }]);
  });
  it("buying the same variant at the same price merges into one line (the backend refuses duplicates)", () => {
    const r = addLine(addLine([], ok).lines, { ...ok, qty: "3" });
    expect(r.lines).toHaveLength(1);
    expect(r.lines[0]).toMatchObject({ qty: 5, total: "250.00" });
  });
  it("the same variant at a DIFFERENT price is refused instead of silently averaged", () => {
    const r = addLine(addLine([], ok).lines, { ...ok, unitCost: "60" });
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(/سعر مختلف/);
  });
  it.each([
    [{ qty: "0" }, /الكمية/], [{ qty: "1e3" }, /الكمية/], [{ qty: "2.5" }, /الكمية/],
    [{ unitCost: "5.005" }, /سعر الشراء/], [{ unitCost: "-1" }, /سعر الشراء/], [{ unitCost: "" }, /سعر الشراء/],
    [{ variantId: "" }, /اختر الصنف/],
  ])("refuses %j", (patch, msg) => {
    const r = addLine([], { ...ok, ...patch });
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(msg);
  });
  it("a free line (cost 0) is allowed", () => {
    expect(addLine([], { ...ok, unitCost: "0" }).lines[0]).toMatchObject({ unitCost: "0.00", total: "0.00" });
  });
  it("does not mutate the lines it was given", () => {
    const before = addLine([], ok).lines;
    const snapshot = JSON.stringify(before);
    addLine(before, { ...ok, qty: "4" });
    expect(JSON.stringify(before)).toBe(snapshot);
  });
});

describe("buildPurchaseOrder", () => {
  const lines = addLine([], { variantId: V1, label: "x", qty: "2", unitCost: "50" }).lines;
  const form = { supplierId: "s1", date: "2026-10-21", lines, note: "  شحنة  " };
  it("builds the wire payload: quantities as text, costs exact, received by default", () => {
    expect(buildPurchaseOrder(form)).toEqual({
      ok: true,
      payload: {
        supplier_id: "s1",
        order_date: "2026-10-21",
        receive_now: true,
        note: "شحنة",
        lines: [{ variant_id: V1, quantity: "2", unit_cost: "50.00" }],
      },
    });
  });
  it("a draft can be requested explicitly", () => expect(buildPurchaseOrder({ ...form, receiveNow: false }).payload.receive_now).toBe(false));
  it.each([
    [{ supplierId: "" }, /المورد/], [{ lines: [] }, /بندًا/], [{ date: "" }, /تاريخ/], [{ date: "21/10/2026" }, /تاريخ/],
    [{ note: "x".repeat(256) }, /255/],
  ])("refuses %j", (patch, msg) => {
    const r = buildPurchaseOrder({ ...form, ...patch });
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(msg);
  });
});

describe("buildPayment", () => {
  const base = { supplierId: "s1", amount: "400", method: "bank_transfer", orderId: "po1" };
  it("a non-cash payment carries no shift", () => {
    const r = buildPayment(base, { openSessionId: "sess" });
    expect(r.ok).toBe(true);
    expect("session_id" in r.payload).toBe(false);
    expect(r.payload).toMatchObject({ amount: "400.00", purchase_order_id: "po1" });
  });
  it("a cash payment is tied to the open shift", () => {
    expect(buildPayment({ ...base, method: "cash" }, { openSessionId: "sess" }).payload.session_id).toBe("sess");
  });
  it("a cash payment with no open shift is stopped here with something the cashier can act on", () => {
    const r = buildPayment({ ...base, method: "cash" }, { openSessionId: null });
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(/وردية/);
  });
  it("cannot pay more than what is owed, to the cent", () => {
    expect(buildPayment({ ...base, amount: "600.01" }, { owed: "600.00" }).ok).toBe(false);
    expect(buildPayment({ ...base, amount: "600.00" }, { owed: "600.00" }).ok).toBe(true);
  });
  it.each([[{ supplierId: "" }, /المورد/], [{ amount: "0" }, /المبلغ/], [{ amount: "10.005" }, /المبلغ/], [{ method: "crypto" }, /طريقة/]])(
    "refuses %j",
    (patch, msg) => {
      const r = buildPayment({ ...base, ...patch });
      expect(r.ok).toBe(false);
      expect(r.error).toMatch(msg);
    },
  );
});

describe("buildReturn", () => {
  const base = { supplierId: "s1", settlement: "credit", lines: [{ variantId: V1, qty: "2" }] };
  it("against an order the price is the order's: no unit_cost is sent", () => {
    const r = buildReturn({ ...base, orderId: "po1" });
    expect(r.payload.lines).toEqual([{ variant_id: V1, quantity: "2" }]);
    expect(r.payload.purchase_order_id).toBe("po1");
  });
  it("without an order the price must be typed", () => {
    expect(buildReturn(base).ok).toBe(false);
    expect(buildReturn({ ...base, lines: [{ variantId: V1, qty: "2", unitCost: "12.5" }] }).payload.lines[0].unit_cost).toBe("12.50");
  });
  it.each([
    [{ settlement: "gift" }, /التسوية/], [{ lines: [] }, /بندًا/],
    [{ lines: [{ variantId: V1, qty: "0" }] }, /الكمية/], [{ supplierId: "" }, /المورد/],
  ])("refuses %j", (patch, msg) => {
    const r = buildReturn({ ...base, orderId: "po1", ...patch });
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(msg);
  });
});

const api = (o = {}) => ({
  id: "o1", number: "PO-2026-0001", supplier_id: "s1", warehouse_id: "w1", order_date: "2026-10-20", status: "received",
  total: "1000.00", paid: "400.00", payment_status: "partial", balance: "600.00", note: null, lines: [
    { variant_id: V1, quantity: 10, unit_cost: "100.00", line_total: "1000.00" },
  ], ...o,
});

describe("mapping", () => {
  it("an order keeps receipt and payment as two separate facts", () => {
    const o = orderFromApi(api(), { suppliers: { s1: "النيل" }, variants: { [V1]: { productName: "تيشيرت", color: "أسود", size: "L" } } });
    expect(o).toMatchObject({ receipt: "received", payment: "partial", supplierName: "النيل", pieces: 10, total: "1000.00", balance: "600.00" });
    expect(o.items[0]).toMatchObject({ name: "تيشيرت", color: "أسود", size: "L" });
  });
  it("received but UNPAID is a normal state (buying on credit)", () => {
    const o = orderFromApi(api({ paid: "0.00", payment_status: "unpaid", balance: "1000.00" }));
    expect(o.receipt).toBe("received");
    expect(o.payment).toBe("unpaid");
  });
  it("unknown supplier / variant degrade to a dash instead of crashing", () => {
    const o = orderFromApi(api());
    expect(o.supplierName).toBe("—");
    expect(o.items[0].name).toBe("—");
  });
  it("a supplier's figures come from the backend statement, as exact text", () => {
    const s = supplierFromApi({ id: "s1", name: "النيل", status: "active", statement: { total_supplied: "1000.00", orders_count: 1, last_order_date: "2026-10-20", items_count: 3, paid: "400.00", credit_returns: "0.00", balance: "600.00" } });
    expect(s).toMatchObject({ total: "1000.00", balance: "600.00", items: 3, lastDeal: "2026-10-20" });
  });
  it("a supplier with no statement yet shows zeros, not undefined", () => {
    expect(supplierFromApi({ id: "s", name: "x", status: "active" })).toMatchObject({ total: "0.00", balance: "0.00", items: 0, lastDeal: null });
  });
  it("a return is mapped with its order number", () => {
    const r = returnFromApi(
      { id: "r1", number: "SR-1", supplier_id: "s1", purchase_order_id: "o1", settlement: "credit", status: "review", total: "240.00", return_date: "2026-10-20", lines: [{ variant_id: V1, quantity: 3, unit_cost: "80.00", line_total: "240.00" }] },
      { suppliers: { s1: "النيل" }, orders: { o1: "PO-2026-0001" } },
    );
    expect(r).toMatchObject({ poNumber: "PO-2026-0001", supplierName: "النيل", qty: 3, amount: "240.00" });
  });
});

describe("summaries count only what is real", () => {
  const rows = [
    orderFromApi(api({ id: "a", total: "0.10", paid: "0.00", balance: "0.10", payment_status: "unpaid" })),
    orderFromApi(api({ id: "b", total: "0.20", paid: "0.00", balance: "0.20", payment_status: "unpaid" })),
    orderFromApi(api({ id: "c", status: "cancelled", total: "9999.00", paid: "0.00", balance: "0.00", payment_status: "unpaid" })),
    orderFromApi(api({ id: "d", status: "draft", total: "5000.00", paid: "0.00", balance: "0.00", payment_status: "unpaid" })),
  ];
  const s = purchasesSummary(rows);
  it("0.1 + 0.2 is 0.30 (no float drift)", () => expect(s.total).toBe("0.30"));
  it("a cancelled or draft order is not supplied goods and owes nothing", () => {
    expect(s).toMatchObject({ count: 4, receivedCount: 2, balance: "0.30" });
  });
  it("an empty list is zero, not NaN", () => expect(purchasesSummary([])).toMatchObject({ total: "0.00", balance: "0.00", pieces: 0 }));
  it("suppliers: debt and credit are kept apart, not netted into a misleading number", () => {
    const sup = suppliersSummary([
      { status: "active", total: "100.00", balance: "300.00" },
      { status: "active", total: "50.00", balance: "-100.00" },
      { status: "inactive", total: "10.00", balance: "0.00" },
    ]);
    expect(sup).toMatchObject({ count: 3, active: 2, total: "160.00", owed: "300.00", inCredit: "-100.00" });
  });
  it("returns: money counts only once the supplier accepted", () => {
    const r = returnsSummary([
      { status: "review", settlement: "credit", amount: "100.00", qty: 1 },
      { status: "accepted", settlement: "credit", amount: "240.00", qty: 3 },
      { status: "accepted", settlement: "cash", amount: "80.00", qty: 2 },
      { status: "rejected", settlement: "credit", amount: "500.00", qty: 5 },
    ]);
    expect(r).toMatchObject({ count: 4, review: 1, pendingAmount: "100.00", credit: "240.00", cash: "80.00" });
  });
});

describe("filterOrders", () => {
  const rows = [
    orderFromApi(api({ id: "1", number: "PO-2026-0001" }), { suppliers: { s1: "النيل" } }),
    orderFromApi(api({ id: "2", number: "PO-2026-0002", supplier_id: "s2", payment_status: "unpaid", paid: "0.00" }), { suppliers: { s2: "دلتا" } }),
    orderFromApi(api({ id: "3", number: "PO-2026-0003", status: "draft", payment_status: "unpaid" })),
  ];
  it("searches number and supplier", () => {
    expect(filterOrders(rows, { term: "0002" })).toHaveLength(1);
    expect(filterOrders(rows, { term: "دلتا" })).toHaveLength(1);
  });
  it("filters receipt and payment independently", () => {
    expect(filterOrders(rows, { receipt: "draft" })).toHaveLength(1);
    expect(filterOrders(rows, { payment: "unpaid" })).toHaveLength(2);
    expect(filterOrders(rows, { receipt: "received", payment: "unpaid" })).toHaveLength(1);
  });
});

describe("purchasingErrorMessage", () => {
  it.each([
    [{ status: 409, message: "this purchase order is already received" }, /اتسجلت/],
    [{ status: 409, message: "a received purchase order cannot be cancelled: register a supplier return instead" }, /مرتجع/],
    [{ status: 409, message: "the payment (700.00) is more than what is still owed on the order (600.00)" }, /المتبقي/],
    [{ status: 409, message: "a cash payment comes out of an open shift: open a shift first" }, /وردية/],
    [{ status: 409, message: "line 1: returning 6 but only 5 of the 5 bought on that order are still returnable" }, /المتاح/],
    [{ status: 409, message: "this return was already accepted" }, /اتحسم/],
    [{ status: 409, message: "a supplier named 'x' already exists" }, /نفس الاسم/],
    [{ status: 409, message: "Idempotency-Key reused with a different request body" }, /بيانات مختلفة/],
    [{ status: 403, message: "forbidden" }, /صلاحية/],
    [{ status: 0, message: "network" }, /الاتصال/],
  ])("%j", (err, re) => expect(purchasingErrorMessage(err)).toMatch(re));
  it("unknown errors keep their text; empty gets a fallback", () => {
    expect(purchasingErrorMessage({ status: 400, message: "شيء غريب" })).toBe("شيء غريب");
    expect(purchasingErrorMessage({})).toBe("حصل خطأ غير متوقع");
  });
});
