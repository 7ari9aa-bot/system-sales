import { describe, expect, it, vi } from "vitest";
import { fingerprint } from "./intentStore";
import { newIntent, posApi } from "./posApi";

vi.mock("@/lib/api", () => ({ api: vi.fn(async () => ({ ok: true })) }));
import { api } from "@/lib/api";
import { sendReturn, tableLine, estimateRefund, estimateRefundMinor, returnErrorMessage, returnRequest, returnableLines, setQty, setLineRestock, setLineCondition, conditionSplit, lineRestock, returnSettlementSummary } from "./returnPlan";

const sale = (over = {}) => ({
  order: { id: "o1", grand_total: "340.00", discount_total: "20.00" },
  lines: [{ variant_id: "v1", title: "قميص", sku: "SH-1", quantity: 3, unit_price: "120.00", total: "360.00", returned_qty: 0 }],
  ...over,
});

describe("returnableLines", () => {
  it("max = sold - already returned", () => {
    const l = returnableLines(sale({ lines: [{ variant_id: "v1", title: "x", quantity: 3, unit_price: "10.00", returned_qty: 2 }] }));
    expect(l[0]).toMatchObject({ sold: 3, alreadyReturned: 2, maxQty: 1, returnQty: 0 });
  });
  it("fully returned line has nothing left", () => {
    expect(returnableLines(sale({ lines: [{ variant_id: "v", quantity: 1, unit_price: "5.00", returned_qty: 1 }] }))[0].maxQty).toBe(0);
  });
  it("never goes negative", () => {
    expect(returnableLines(sale({ lines: [{ variant_id: "v", quantity: 1, unit_price: "5.00", returned_qty: 9 }] }))[0].maxQty).toBe(0);
  });
});

describe("setQty", () => {
  const base = returnableLines(sale());
  it("clamps to the available quantity", () => expect(setQty(base, "v1", 99)[0].returnQty).toBe(3));
  it("clamps below zero and garbage to 0", () => {
    expect(setQty(base, "v1", -4)[0].returnQty).toBe(0);
    expect(setQty(base, "v1", "abc")[0].returnQty).toBe(0);
    expect(setQty(base, "v1", 1.9)[0].returnQty).toBe(1);
  });
  it("touches only its own line", () => {
    const two = returnableLines(sale({ lines: [{ variant_id: "a", quantity: 2, unit_price: "1.00" }, { variant_id: "b", quantity: 2, unit_price: "1.00" }] }));
    const r = setQty(two, "a", 2);
    expect([r[0].returnQty, r[1].returnQty]).toEqual([2, 0]);
  });
});

describe("estimateRefund follows the backend's proportional-discount rule", () => {
  const withQty = (s, q) => setQty(returnableLines(s), "v1", q);
  it("no discount -> plain price", () => {
    const s = sale({ order: { id: "o", discount_total: "0.00" } });
    expect(estimateRefund(s, withQty(s, 2))).toBe("240.00");
  });
  it("discount 20 on 360 subtotal: 1 unit refunds 120 - 6.67 = 113.33", () => {
    const s = sale();
    expect(estimateRefund(s, withQty(s, 1))).toBe("113.33");
  });
  it("returning everything refunds exactly the amount paid (360 - 20)", () => {
    const s = sale();
    expect(estimateRefund(s, withQty(s, 3))).toBe("340.00");
  });
  it("nothing selected -> 0", () => expect(estimateRefundMinor(sale(), returnableLines(sale()))).toBe(0));
  it("rounds half up per line like the backend", () => {
    // 10.00 x1 line, subtotal 30.00 (3 lines of 10), discount 1.00 -> share 0.3333 -> 0.33 ; refund 9.67
    const s = { order: { id: "o", discount_total: "1.00" }, lines: [{ variant_id: "v1", quantity: 1, unit_price: "10.00" }, { variant_id: "v2", quantity: 2, unit_price: "10.00" }] };
    expect(estimateRefund(s, setQty(returnableLines(s), "v1", 1))).toBe("9.67");
  });
});

describe("returnRequest", () => {
  it("sends only picked lines and the restock choice", () => {
    const s = sale();
    const req = returnRequest(s, setQty(returnableLines(s), "v1", 2), { restock: true });
    expect(req).toEqual({ orderId: "o1", lines: [{ variant_id: "v1", quantity: 2, condition: "sellable" }], restock: true });
  });
  it("leaves restock out until the cashier chooses, so the shop's own default applies", () => {
    const s = sale();
    const req = returnRequest(s, setQty(returnableLines(s), "v1", 1), {});
    expect("restock" in req).toBe(false);
  });
  it("sends an explicit no-restock when the cashier chose it", () => {
    const s = sale();
    expect(returnRequest(s, setQty(returnableLines(s), "v1", 1), { restock: false }).restock).toBe(false);
  });
  it("puts the chosen reason on every returned line, and none when there is no reason", () => {
    const s = sale();
    const picked = setQty(returnableLines(s), "v1", 1);
    expect(returnRequest(s, picked, { reason: "size" }).lines[0].reason).toBe("size");
    expect("reason" in returnRequest(s, picked, {}).lines[0]).toBe(false);
    expect("reason" in returnRequest(s, picked, { reason: null }).lines[0]).toBe(false);
  });
  it("a piece with no shelf choice of its own sends none, so the whole return's choice applies", () => {
    const s = sale();
    const req = returnRequest(s, setQty(returnableLines(s), "v1", 1), { restock: true });
    expect("restock" in req.lines[0]).toBe(false);
  });
  it("a piece with its own shelf choice sends it on its line, including an explicit no", () => {
    const s = sale();
    const picked = setLineRestock(setQty(returnableLines(s), "v1", 1), "v1", false);
    expect(returnRequest(s, picked, { restock: true }).lines[0].restock).toBe(false);
    expect(returnRequest(s, setLineRestock(picked, "v1", true), {}).lines[0].restock).toBe(true);
  });
  it("clearing a piece's choice sends nothing for it again", () => {
    const s = sale();
    const picked = setLineRestock(setLineRestock(setQty(returnableLines(s), "v1", 1), "v1", false), "v1", null);
    expect("restock" in returnRequest(s, picked, {}).lines[0]).toBe(false);
  });
  it("refuses an empty return", () => {
    expect(() => returnRequest(sale(), returnableLines(sale()), { restock: false })).toThrow();
  });
});

describe("returnErrorMessage", () => {
  it("explains the different-session rule", () => expect(returnErrorMessage(new Error("this sale belongs to a different session"))).toMatch(/وردية أخرى/));
  it("explains a closed shift", () => expect(returnErrorMessage(new Error("this session is closed; returns ride the open drawer"))).toMatch(/مغلقة/));
  it("never hides an unknown error", () => expect(returnErrorMessage(new Error("boom 42"))).toBe("boom 42"));
});

describe("tableLine", () => {
  it("keeps the picked quantity and adds what the tables read", () => {
    const l = tableLine({ ...returnableLines(sale())[0], returnQty: 2 });
    expect(l).toMatchObject({ key: "v1", barcode: "SH-1", qty: 3, unitNet: 120, total: 360, returnQty: 2, maxQty: 3 });
  });
  it("shows what was really paid when the line had its own discount (300 at 10% off reads 270)", () => {
    const s = sale({ lines: [{ variant_id: "v1", title: "x", sku: "S", quantity: 2, unit_price: "300.00", discount_pct: "10.00", returned_qty: 0 }] });
    const l = tableLine({ ...returnableLines(s)[0], returnQty: 1 });
    expect(l).toMatchObject({ unitNet: 270, total: 540 });
    expect(Number(estimateRefund(s, [{ ...returnableLines(s)[0], returnQty: 1 }]))).toBe(l.unitNet);
  });
  it("a line without a discount is unchanged", () => {
    const l = tableLine(returnableLines(sale())[0]);
    expect(l).toMatchObject({ unitNet: 120, total: 360 });
  });
  it("does not invent size or colour", () => {
    const l = tableLine(returnableLines(sale())[0]);
    expect([l.size, l.color]).toEqual(["", ""]);
  });
});

describe("a planned return is accepted by the real posApi.returnSale (contract)", () => {
  it("builds a request the client sends as-is to /returns", async () => {
    const s = sale();
    const req = returnRequest(s, setQty(returnableLines(s), "v1", 2), { restock: false });
    await posApi.returnSale("sess-1", req, newIntent());
    const [path, opts] = api.mock.calls.at(-1);
    expect(path).toBe("/pos/sessions/sess-1/returns");
    expect(opts.body).toEqual({ order_id: "o1", lines: [{ variant_id: "v1", quantity: 2, condition: "sellable" }], restock: false });
    expect(opts.headers["Idempotency-Key"]).toMatch(/^pos-/);
  });
});

describe("sendReturn", () => {
  const noWait = { sleep: async () => {} };
  it("passes a normal success through, one call", async () => {
    const send = vi.fn(async () => ({ ok: 1 }));
    expect(await sendReturn(send, noWait)).toEqual({ ok: 1 });
    expect(send).toHaveBeenCalledTimes(1);
  });
  it("retries while the same intent is in progress, then returns the replayed answer", async () => {
    const send = vi.fn().mockRejectedValueOnce(new Error("request with this Idempotency-Key is in progress")).mockResolvedValueOnce({ n: "POS-RET-1" });
    expect(await sendReturn(send, noWait)).toEqual({ n: "POS-RET-1" });
    expect(send).toHaveBeenCalledTimes(2);
  });
  it("gives up after the tries and surfaces the error", async () => {
    const send = vi.fn().mockRejectedValue(new Error("request with this Idempotency-Key is in progress"));
    await expect(sendReturn(send, { ...noWait, tries: 3 })).rejects.toThrow(/in progress/);
    expect(send).toHaveBeenCalledTimes(3);
  });
  it("does NOT retry a real refusal", async () => {
    const send = vi.fn().mockRejectedValue(new Error("this sale belongs to a different session"));
    await expect(sendReturn(send, noWait)).rejects.toThrow(/different session/);
    expect(send).toHaveBeenCalledTimes(1);
  });
});

describe("estimateRefundMinor with per-item discounts (report example)", () => {
  // A: 100 at 50% off = 50 paid. B: 100 no discount. Invoice total 150.
  const sale = (extra = {}) => ({
    order: { discount_total: "50.00", grand_total: "150.00", ...extra },
    lines: [
      { variant_id: "A", title: "A", quantity: 1, unit_price: "100.00", discount_pct: "50.00", returned_qty: 0 },
      { variant_id: "B", title: "B", quantity: 1, unit_price: "100.00", discount_pct: "0.00", returned_qty: 0 },
    ],
  });
  const pick = (d, id, qty) => returnableLines(d).map((l) => (l.variantId === id ? { ...l, returnQty: qty } : l));

  it("returning the 50%-off item refunds 50, not 75 or 100", () => {
    const d = sale();
    expect(estimateRefund(d, pick(d, "A", 1))).toBe("50.00");
  });
  it("returning the full-price item refunds 100", () => {
    const d = sale();
    expect(estimateRefund(d, pick(d, "B", 1))).toBe("100.00");
  });
  it("exchange difference: A (50 paid) swapped for a 60 item is +10", () => {
    const d = sale();
    expect(Number(estimateRefund(d, pick(d, "A", 1))) - 60).toBe(-10);
  });
  it("an invoice-level discount on top is shared over the NET of the lines, per the backend", () => {
    // gross 200, A has 50% off (net 150). Invoice discount 15 beyond the line discount.
    const d = sale({ discount_total: "65.00" });
    // order_level = 65 - (200-150) = 15 ; A net 50 -> share 15*50/150 = 5.00 -> refund 45.00
    expect(estimateRefund(d, pick(d, "A", 1))).toBe("45.00");
  });
  it("partial quantity rounds half up to cents", () => {
    const d = { order: { discount_total: "0.00" }, lines: [{ variant_id: "C", title: "C", quantity: 3, unit_price: "33.33", discount_pct: "0.00", returned_qty: 0 }] };
    expect(estimateRefund(d, pick(d, "C", 2))).toBe("66.66");
  });

});

describe("lineRestock", () => {
  it("shows the piece's own choice, else the whole return's", () => {
    expect(lineRestock({ restock: null }, true)).toBe(true);
    expect(lineRestock({ restock: null }, false)).toBe(false);
    expect(lineRestock({}, true)).toBe(true);
    expect(lineRestock({ restock: false }, true)).toBe(false);
    expect(lineRestock({ restock: true }, false)).toBe(true);
  });

});

describe("the piece's condition", () => {
  it("defaults to sellable so a returned piece is never silently quarantined", () => {
    const s = sale();
    const lines = setQty(returnableLines(s), "v1", 2);
    expect(lines[0].condition).toBe("sellable");
    expect(returnRequest(s, lines, {}).lines[0].condition).toBe("sellable");
  });

  it("sends the condition the cashier picked, per line", () => {
    const s = sale();
    const lines = setLineCondition(setQty(returnableLines(s), "v1", 1), "v1", "damaged");
    expect(returnRequest(s, lines, {}).lines[0]).toEqual({ variant_id: "v1", quantity: 1, condition: "damaged" });
  });

  it("splits the picked units by condition for the summary", () => {
    const s = sale({ lines: [
      { variant_id: "v1", title: "قميص", quantity: 2, unit_price: "100.00", returned_qty: 0 },
      { variant_id: "v2", title: "بنطلون", quantity: 1, unit_price: "200.00", returned_qty: 0 },
    ] });
    let lines = setQty(returnableLines(s), "v1", 2);
    lines = setQty(lines, "v2", 1);
    lines = setLineCondition(lines, "v2", "writeoff");
    expect(conditionSplit(lines)).toEqual([
      expect.objectContaining({ value: "sellable", units: 2 }),
      expect.objectContaining({ value: "writeoff", units: 1 }),
    ]);
  });
});

describe("what the server did with the money", () => {
  it("says the amount was refunded and where it came from", () => {
    const text = returnSettlementSummary({ refund_mode: "tender", refunded: "150.00", refund_by_method: { cash: "50.00", card: "100.00" }, refund_uncollected: "0.00" });
    expect(text).toContain("اترد 150.00");
    expect(text).toContain("نقدي 50.00");
    expect(text).toContain("النقدي خرج من درج الوردية");
  });
  it("says what the sale never collected instead of pretending it was refunded", () => {
    const text = returnSettlementSummary({ refund_mode: "nothing_collected", refunded: "0.00", refund_by_method: {}, refund_uncollected: "80.00" });
    expect(text).toContain("لم تحصّل");
    expect(text).toContain("لم تُحصَّل أصلًا");
  });
  it("a record-only till says the money was only recorded", () => {
    expect(returnSettlementSummary({ refund_mode: "record_only", refunded: "0.00", refund_by_method: {}, refund_uncollected: "40.00" }))
      .toContain("أمين الصندوق لا يسجّل مدفوعات");
  });
});

describe("the return key follows the whole body", () => {
  // The screen fingerprinted a hand-picked list that left out the piece condition, so fixing the
  // condition after a refusal reused the old key and the server answered 409 for a different body.
  const sale = {
    order: { id: "o1" },
    lines: [{ variant_id: "v1", title: "قميص", sku: "SH", quantity: 2, unit_price: "100.00", returned_qty: 0 }],
  };
  const line = (condition) => {
    const picked = setQty(returnableLines(sale), "v1", 1);
    return picked.map((l) => ({ ...l, condition }));
  };

  it("a changed condition is a different intention", () => {
    const a = fingerprint(returnRequest(sale, line("sellable"), { restock: true }));
    const b = fingerprint(returnRequest(sale, line("damaged"), { restock: true }));
    expect(a).not.toBe(b);
  });

  it("an identical resend keeps the key", () => {
    const a = fingerprint(returnRequest(sale, line("sellable"), { restock: true }));
    const b = fingerprint(returnRequest(sale, line("sellable"), { restock: true }));
    expect(a).toBe(b);
  });
});

describe("what the message says about money not yet returned", () => {
  // The report's blocker 2: a pending card reversal was announced as refunded.
  const base = {
    refund_mode: "tender",
    refunded: "100.00",
    refund_by_method: { card: "100.00" },
    refund_uncollected: "0.00",
  };

  it("names the pending card slice as still waiting for the terminal", () => {
    const text = returnSettlementSummary({
      ...base,
      refunded: "0.00",
      refund_by_method: {},
      awaiting_confirmation: [{ refund_id: "r1", method: "card", amount: "100.00" }],
    });
    expect(text).toContain("اترد 0.00");
    expect(text).toContain("لا تزال تنتظر تأكيد الماكينة");
  });

  it("counts only the confirmed part as refunded when it is split", () => {
    const text = returnSettlementSummary({
      ...base,
      refunded: "40.00",
      refund_by_method: { cash: "40.00", card: "60.00" },
      awaiting_confirmation: [{ refund_id: "r1", method: "card", amount: "60.00" }],
    });
    expect(text).toContain("اترد 40.00");
    expect(text).toContain("60.00");
  });

  it("tells the cashier the manual amount for a cash-only shop", () => {
    const text = returnSettlementSummary({
      refund_mode: "cash_only",
      refunded: "0.00",
      refund_by_method: {},
      refund_uncollected: "0.00",
      terminal_only: [{ method: "card", amount: "30.00" }],
    });
    expect(text).toContain("30.00");
    expect(text).toContain("يدويًا");
  });
});

describe("returnSettlementSummary — the confirmed money", () => {
  const result = (over = {}) => ({
    refund_mode: "refund",
    refund_total: "100.00",
    refunded: "50.00",
    refund_uncollected: "0.00",
    refund_by_method: { cash: "50.00", card: "50.00" },
    awaiting_confirmation: [{ refund_id: "r2", method: "card", amount: "50.00" }],
    ...over,
  });

  it("counts what left the drawer as returned even while a card slice is pending", () => {
    // 50 cash went back, 50 card is still on the terminal: the summary must say 50 returned,
    // not zero. Subtracting the pending slice from `refunded` again showed zero.
    const text = returnSettlementSummary(result());
    expect(text).toContain("اترد 50.00");
    expect(text).not.toContain("اترد 0.00");
  });

  it("still says nothing was returned when the whole refund is pending", () => {
    const text = returnSettlementSummary(
      result({ refunded: "0.00", refund_by_method: {}, awaiting_confirmation: [{ refund_id: "r1", method: "card", amount: "100.00" }] }),
    );
    expect(text).toContain("اترد 0.00");
  });
});
