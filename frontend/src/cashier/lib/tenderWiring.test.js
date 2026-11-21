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

describe("receipts reach the printer as a picture", () => {
  it("neither print path sends raw text bytes, which print Arabic as symbols", () => {
    for (const rel of ["routes/_authed/pos.jsx", "components/pos/PrinterSetupDialog.jsx"]) {
      const src = read(rel);
      expect(src, rel).toMatch(/receiptBytes\(/);
      expect(src, rel).not.toMatch(/buildReceiptEscPos/);
    }
  });
});

describe("the shop's own policy is not written in the receipt screen", () => {
  const dialog = read("components/pos/ReceiptDialog.jsx");
  const pos = read("routes/_authed/pos.jsx");
  const adapter = read("api/receiptAdapter.js");

  it("the preview does not promise a fixed exchange period", () => {
    expect(dialog).not.toMatch(/الاستبدال خلال/);
    expect(dialog).not.toMatch(/١٤|14 ?يوم/);
  });

  it("the preview writes the currency from the order, the Egyptian pound only as a last resort", () => {
    expect(dialog).toMatch(/currencyLabel\(receipt\.currency\)/);
    expect(dialog.match(/ج\.م/g)?.length).toBe(1);
  });

  it("the preview and the printed copy read the same shop block", () => {
    expect(dialog).toMatch(/receipt\.shop/);
    expect(pos).toMatch(/printableReceipt\(r,/);
    expect(adapter).toMatch(/shop: receiptShop\(shop\)/);
  });

  it("the sale screen prints as many copies as the owner set", () => {
    expect(pos).toMatch(/r\?\.shop\?\.copies/);
  });

  it("the paper width is the shop's, not a number the sale screen picks", () => {
    expect(pos).not.toMatch(/paperMm\s*[:=]\s*(58|80)/);
  });
});

describe("the shop's currency reaches every amount", () => {
  const auth = readFileSync(new URL("../../lib/AuthContext.jsx", import.meta.url), "utf8");
  const format = read("lib/format.js");

  it("the signed-in shop's currency is set whenever the user changes", () => {
    expect(auth).toMatch(/setShopCurrency\(user\?\.tenants\?\.length === 1 \? user\.tenants\[0\]\.currency : undefined\)/);
    expect(auth).toMatch(/\[user\]\);/);
  });

  it("amounts are written with the sign that was set, not a literal", () => {
    expect(format).toMatch(/\$\{CURRENCY\}/);
    expect(format.match(/ج\.م/g)?.length).toBe(1);
  });
});

