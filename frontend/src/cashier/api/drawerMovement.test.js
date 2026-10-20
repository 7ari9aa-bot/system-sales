import { describe, expect, it } from "vitest";
import { MOVEMENT_KINDS, normalizeAmountText, planMovement } from "./drawerMovement";

describe("normalizeAmountText", () => {
  it("accepts Arabic-Indic digits and the Arabic decimal separator", () => {
    expect(normalizeAmountText("٥٠٫٥")).toBe("50.5");
    expect(normalizeAmountText(" 12,75 ")).toBe("12.75");
    expect(normalizeAmountText(null)).toBe("");
  });
});

describe("planMovement", () => {
  it("maps each kind to the exact backend direction + reason", () => {
    expect(planMovement({ kind: "pay_in", amount: "100" })).toEqual({ ok: true, direction: "in", reason: "pay_in", amount: "100.00" });
    expect(planMovement({ kind: "pay_out", amount: "20.5" })).toMatchObject({ direction: "out", reason: "pay_out", amount: "20.50" });
    expect(planMovement({ kind: "cash_drop", amount: "٣٠" })).toMatchObject({ direction: "out", reason: "cash_drop", amount: "30.00" });
  });
  it("never offers a reason the sell flow owns", () => {
    expect(MOVEMENT_KINDS.map((k) => k.kind)).not.toContain("cash_sale");
    expect(MOVEMENT_KINDS.map((k) => k.kind)).not.toContain("cash_refund");
    expect(planMovement({ kind: "cash_sale", amount: "10" }).ok).toBe(false);
  });
  it.each(["", "abc", "0", "0.00", "-5", "1e3", "5 0"])("refuses %j before any request", (amount) => {
    expect(planMovement({ kind: "pay_in", amount }).ok).toBe(false);
  });
  it("rounds half-up to 2 places like the backend", () => {
    expect(planMovement({ kind: "pay_in", amount: "10.005" }).amount).toBe("10.01");
  });
  it("blocks taking out more than the drawer should hold, but not paying in", () => {
    expect(planMovement({ kind: "pay_out", amount: "500.01", expectedCash: "500.00" }).ok).toBe(false);
    expect(planMovement({ kind: "pay_out", amount: "500.00", expectedCash: "500.00" }).ok).toBe(true);
    expect(planMovement({ kind: "pay_in", amount: "9999", expectedCash: "1.00" }).ok).toBe(true);
  });
  it("lets the backend judge when the balance is unknown", () => {
    expect(planMovement({ kind: "pay_out", amount: "50", expectedCash: undefined }).ok).toBe(true);
  });
});
