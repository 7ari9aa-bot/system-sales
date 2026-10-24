import { describe, expect, it } from "vitest";
import { INVOICE_STATUS } from "./format";

describe("invoice status wording", () => {
  it("never says a sale was paid: the cashier records sales, it takes no payment", () => {
    for (const { label } of Object.values(INVOICE_STATUS)) expect(label).not.toMatch(/مدفوع/);
    expect(INVOICE_STATUS.paid.label).toBe("مسجّلة");
  });
});
