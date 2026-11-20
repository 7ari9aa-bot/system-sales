import { describe, expect, it } from "vitest";
import { buildTender, canSellOnAccount, changeDue, defaultTender, offlineTenderBlocked, remainingToPay } from "./tenderPlan";

const rules = { take_payments: true, allow_on_account: false, methods: ["cash", "card"], reference_required: ["card"] };
const onAccount = { ...rules, allow_on_account: true };

describe("a till that does not record payments", () => {
  it("sends no payment at all, whatever the screen holds", () => {
    const off = { take_payments: false, allow_on_account: false, methods: [], reference_required: [] };
    expect(buildTender(off, "100.00", [{ method: "cash", amount: "100.00" }])).toEqual({ ok: true, payload: {} });
  });
  it("an unknown rule set (not loaded) is treated as not recording payments", () => {
    expect(buildTender(null, "100.00", [])).toEqual({ ok: true, payload: {} });
  });
});

describe("a till that records payments", () => {
  it("defaults to the whole total in the first method", () => {
    expect(defaultTender(rules, "170.00")).toEqual([{ method: "cash", amount: "170.00", tendered: "", reference: "" }]);
  });

  it("cash handed over above the amount is sent as tendered, change is not a second payment", () => {
    const out = buildTender(rules, "170.00", [{ method: "cash", amount: "170.00", tendered: "200" }]);
    expect(out).toEqual({ ok: true, payload: { payments: [{ method: "cash", amount: "170.00", tendered: "200.00" }] } });
  });

  it("splits across methods and carries the reference only where one is required", () => {
    const out = buildTender(rules, "170.00", [
      { method: "cash", amount: "70.00", tendered: "", reference: "ignored" },
      { method: "card", amount: "100.00", reference: " 4455 " },
    ]);
    expect(out.payload.payments).toEqual([
      { method: "cash", amount: "70.00" },
      { method: "card", amount: "100.00", reference: "4455" },
    ]);
  });

  it.each([
    ["no lines", []],
    ["a method the till does not accept", [{ method: "transfer", amount: "170.00" }]],
    ["a required reference left empty", [{ method: "card", amount: "170.00", reference: " " }]],
    ["less than the total", [{ method: "cash", amount: "100.00" }]],
    ["more than the total", [{ method: "cash", amount: "171.00" }]],
    ["cash handed over below its amount", [{ method: "cash", amount: "170.00", tendered: "150" }]],
    ["a non-cash line tendered above its amount", [{ method: "card", amount: "170.00", reference: "1", tendered: "200" }]],
    ["a zero or invalid amount", [{ method: "cash", amount: "0" }, { method: "card", amount: "170.00", reference: "1" }]],
    ["a negative amount", [{ method: "cash", amount: "-5" }, { method: "card", amount: "175.00", reference: "1" }]],
    ["a non-numeric amount", [{ method: "cash", amount: "abc" }]],
  ])("refuses %s before any request", (_name, lines) => {
    const out = buildTender(rules, "170.00", lines);
    expect(out.ok).toBe(false);
    expect(out.message).toMatch(/[\u0600-\u06FF]/);
    expect(out.message).not.toMatch(/[A-Za-z]{4,}/);
  });

  it("reads Arabic-Indic digits and a comma decimal like the opening balance does", () => {
    const out = buildTender(rules, "170.50", [{ method: "cash", amount: "١٧٠٫٥٠" }]);
    expect(out.payload.payments[0].amount).toBe("170.50");
  });

  it("never sends on_account when it was not asked for", () => {
    const out = buildTender(onAccount, "170.00", [{ method: "cash", amount: "170.00" }]);
    expect(out.payload).not.toHaveProperty("on_account");
  });
});

describe("selling on the customer's account", () => {
  it("is offered only when the till allows it AND a customer is named", () => {
    expect(canSellOnAccount(onAccount, { customerId: "c1" })).toBe(true);
    expect(canSellOnAccount(onAccount, { customerPhone: "01012345678" })).toBe(true);
    expect(canSellOnAccount(onAccount, {})).toBe(false);
    expect(canSellOnAccount(onAccount, { customerPhone: "   " })).toBe(false);
    expect(canSellOnAccount(rules, { customerId: "c1" })).toBe(false);
    expect(canSellOnAccount({ ...onAccount, take_payments: false }, { customerId: "c1" })).toBe(false);
    expect(canSellOnAccount(null, { customerId: "c1" })).toBe(false);
  });

  it("the unpaid rest may be anything up to the whole total, with no payment line at all", () => {
    const part = buildTender(onAccount, "170.00", [{ method: "cash", amount: "50.00" }], { onAccount: true });
    expect(part).toEqual({ ok: true, payload: { payments: [{ method: "cash", amount: "50.00" }], on_account: true } });
    const none = buildTender(onAccount, "170.00", [], { onAccount: true });
    expect(none).toEqual({ ok: true, payload: { on_account: true } });
  });

  it("still refuses paying MORE than the total on account", () => {
    expect(buildTender(onAccount, "170.00", [{ method: "cash", amount: "171.00" }], { onAccount: true }).ok).toBe(false);
  });

  it("refuses an account sale the till does not allow", () => {
    expect(buildTender(rules, "170.00", [], { onAccount: true }).ok).toBe(false);
  });
});

describe("offline", () => {
  it("a till that records payments cannot queue a sale it cannot settle", () => {
    expect(offlineTenderBlocked(rules)).toMatch(/[\u0600-\u06FF]/);
    expect(offlineTenderBlocked({ ...rules, take_payments: false })).toBeNull();
    expect(offlineTenderBlocked(null)).toBeNull();
  });
});

describe("what the cashier sees while entering payment", () => {
  it("the amount still to be covered, never below zero", () => {
    expect(remainingToPay("170.00", [{ method: "cash", amount: "70" }])).toBe("100.00");
    expect(remainingToPay("170.00", [{ method: "cash", amount: "170" }])).toBe("0.00");
    expect(remainingToPay("170.00", [{ method: "cash", amount: "200" }])).toBe("0.00");
    expect(remainingToPay("170.00", [])).toBe("170.00");
  });

  it("a line that is not a number yet counts as nothing, never NaN", () => {
    expect(remainingToPay("170.00", [{ method: "cash", amount: "" }, { method: "card", amount: "abc" }])).toBe("170.00");
  });

  it("the change owed is what cash was handed over above what it covers", () => {
    expect(changeDue([{ method: "cash", amount: "170.00", tendered: "200" }])).toBe("30.00");
    expect(changeDue([{ method: "cash", amount: "170.00", tendered: "" }])).toBe("0.00");
    expect(changeDue([{ method: "cash", amount: "170.00", tendered: "100" }])).toBe("0.00");
    expect(changeDue([{ method: "card", amount: "170.00", tendered: "999" }])).toBe("0.00");
    expect(changeDue([{ method: "cash", amount: "10.10", tendered: "20.20" }])).toBe("10.10");
  });
});

import { saleTender, whenOffline } from "./tenderPlan";

describe("what the screen hands the sale from the dialog's answer", () => {
  it("the dialog's payload becomes the sale's payments and account flag", () => {
    expect(saleTender({ payments: [{ method: "cash", amount: "5.00" }], on_account: true })).toEqual({
      payments: [{ method: "cash", amount: "5.00" }],
      onAccount: true,
    });
  });

  it("a till that records no payment hands over nothing", () => {
    expect(saleTender({})).toEqual({ payments: undefined, onAccount: undefined });
    expect(saleTender(undefined)).toEqual({ payments: undefined, onAccount: undefined });
  });
});

describe("a sale made while the connection is down", () => {
  it("is queued on a till that records no payment", () => {
    expect(whenOffline(null)).toEqual({ queue: true });
    expect(whenOffline({ take_payments: false })).toEqual({ queue: true });
  });

  it("is refused, with the reason, on a till that records payments", () => {
    const out = whenOffline({ take_payments: true });
    expect(out.queue).toBe(false);
    expect(out.message).toMatch(/[\u0600-\u06FF]/);
  });
});
