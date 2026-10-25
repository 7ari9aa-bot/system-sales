import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// The cashier records sales, returns and exchanges. It takes no payment and refunds nothing, so a
// screen must never tell the user money is paid back or owed. A source-level guard, because these
// strings live in components that the test setup cannot render.
const read = (rel) => readFileSync(new URL(`../${rel}`, import.meta.url), "utf8");

describe("screens do not claim money moves", () => {
  it("the return screen does not promise a refund to the customer", () => {
    const src = read("components/returns/ReturnSettlementBar.jsx");
    expect(src).not.toMatch(/يُرد المبلغ/);
    expect(src).not.toMatch(/المستحق للعميل/);
  });
  it("the invoice page only shows payment lines for a sale that recorded a payment", () => {
    const src = read("routes/_authed/sales.$invoiceId.jsx");
    expect(src).toMatch(/invoice\.hasPayment && \(/);
    expect(src.match(/hasPayment/g).length).toBeGreaterThanOrEqual(2);
  });
});
