import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ConfirmSaleBody } from "./ConfirmSaleDialog";
import { readFileSync } from "node:fs";

const html = (props) =>
  renderToStaticMarkup(createElement(ConfirmSaleBody, { total: "120.00", onBack: () => {}, onConfirm: () => {}, ...props }));

describe("ConfirmSaleDialog: confirm a sale, nothing to pay", () => {
  it("shows the invoice total and the confirm button", () => {
    const h = html({});
    expect(h).toContain("إجمالي الفاتورة");
    expect(h).toContain("تأكيد البيع وطباعة الفاتورة");
  });

  it("asks for no amount, no change and no payment method", () => {
    const h = html({});
    expect(h).not.toMatch(/<input/);
    expect(h).not.toContain("المبلغ المدفوع");
    expect(h).not.toMatch(/الباقي|المتبقي|بطاقة|محفظة/);
  });

  it("is disabled while pending and for a zero total; an error is shown", () => {
    expect(html({ pending: true })).toMatch(/<button[^>]*disabled[^>]*>[^<]*جارٍ تسجيل البيع/);
    expect(html({ total: "0.00" })).toMatch(/<button[^>]*disabled[^>]*>[^<]*تأكيد البيع/);
    expect(html({ error: "المخزون غير كاف" })).toContain("المخزون غير كاف");
  });
});

describe("ConfirmSaleDialog on a till that records payments", () => {
  const rules = { take_payments: true, allow_on_account: false, methods: ["cash", "card"], reference_required: ["card"] };
  const on = (props) => html({ rules, ...props });

  it("shows the methods the till accepts, and nothing else", () => {
    const h = on({});
    expect(h).toContain("طريقة الدفع");
    expect(h).toContain("نقدي");
    expect(h).toContain("بطاقة");
    expect(h).not.toContain("تحويل");
    expect(h).not.toContain("على الحساب");
  });

  it("starts with the whole total in the first method and nothing left to pay", () => {
    const h = on({});
    expect(h).toContain('value="120.00"');
    expect(h).toMatch(/المتبقي<\/span><span[^>]*>0\.00</);
  });

  it("asks for the reference only on a method that needs one", () => {
    expect(on({ initialLines: [{ method: "card", amount: "120.00", tendered: "", reference: "" }] })).toContain("رقم المرجع");
    expect(on({})).not.toContain("رقم المرجع");
  });

  it("offers the account only when the till allows it and a customer is named", () => {
    const acct = { ...rules, allow_on_account: true };
    expect(html({ rules: acct, customer: { customerId: "c1" } })).toContain("على الحساب");
    expect(html({ rules: acct, customer: {} })).not.toContain("على الحساب");
  });

  it("the confirm button waits for a valid tender", () => {
    const short = on({ initialLines: [{ method: "cash", amount: "50", tendered: "", reference: "" }] });
    expect(short).toMatch(/<button[^>]* disabled=""[^>]*>تأكيد البيع/);
    expect(short).toContain("المدفوع أقل من الإجمالي");
    expect(on({})).not.toMatch(/<button[^>]* disabled=""[^>]*>تأكيد البيع/);
  });

  it("shows the change owed on cash handed over", () => {
    const h = on({ initialLines: [{ method: "cash", amount: "120.00", tendered: "200", reference: "" }] });
    expect(h).toMatch(/الباقي للعميل<\/span><span[^>]*>80\.00</);
  });

  it("a method already on the invoice is not offered again", () => {
    const h = on({ initialLines: [{ method: "cash", amount: "60.00", tendered: "", reference: "" }, { method: "card", amount: "60.00", tendered: "", reference: "1" }] });
    expect(h).not.toMatch(/\+ (نقدي|بطاقة)/);
    expect(on({})).toContain("+ بطاقة");
    expect(on({})).not.toContain("+ نقدي");
  });

  it("the dialog hands its body the named customer, or the account option can never appear", () => {
    const src = readFileSync(new URL("./ConfirmSaleDialog.jsx", import.meta.url), "utf8");
    expect(src).toMatch(/<ConfirmSaleBody[\s\S]*?customer=\{customer\}[\s\S]*?\/>/);
  });
});
