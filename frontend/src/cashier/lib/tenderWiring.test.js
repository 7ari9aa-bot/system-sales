import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// The sale screen is JSX the test setup cannot render, so the wiring that carries a payment from the
// dialog to the server is guarded at the source: a broken link here books a card sale as cash.
const read = (rel) => readFileSync(new URL(`../${rel}`, import.meta.url), "utf8");

describe("a payment entered in the dialog reaches the server", () => {
  const pos = read("routes/_authed/pos.jsx");
  const hook = read("api/usePosSale.js");
  const dialog = read("components/pos/ConfirmSaleDialog.jsx");

  it("the screen gives the dialog the till's rules and the named customer", () => {
    expect(pos).toMatch(/rules=\{session\.tender\}/);
    expect(pos).toMatch(/customer=\{\{ customerId: pickedCustomer\?\.id, customerPhone \}\}/);
  });

  it("the dialog's answer is what the sale is recorded with", () => {
    expect(pos).toMatch(/async function confirmSale\(tender = \{\}\)/);
    expect(pos).toMatch(/\.\.\.saleTender\(tender\)/);
    expect(dialog).toMatch(/onConfirm\(plan\.payload\)/);
  });

  it("the hook hands the payment on to the sale", () => {
    expect(hook).toMatch(/customerPhone, payments, onAccount \} = \{\}\)/);
    expect(hook).toMatch(/payments,\s*\n\s*onAccount,\s*\n\s*\}\);/);
  });

  it("a sale cannot be queued offline on a till that records payments, in both places it was queued", () => {
    expect(pos.match(/whenOffline\(session\.tender\)/g)?.length).toBe(2);
    expect(pos).toMatch(/if \(!offline\.queue\)/);
  });

  it("the dialog is re-created for a new total, never reused with a stale tender", () => {
    expect(dialog).toMatch(/<ConfirmSaleBody key=\{`\$\{total\}`\}/);
  });
});

describe("the dialog only offers what the till allows", () => {
  const dialog = read("components/pos/ConfirmSaleDialog.jsx");
  it("the account option is gated on both the setting and a named customer", () => {
    expect(dialog).toMatch(/\{accountOk \? \(/);
    expect(dialog).toMatch(/\{ onAccount: onAccount && accountOk \}/);
  });
  it("the confirm button waits for a valid tender", () => {
    expect(dialog).toMatch(/disabled=\{pending \|\| !\(Number\(total\) > 0\) \|\| !plan\.ok\}/);
  });
});
