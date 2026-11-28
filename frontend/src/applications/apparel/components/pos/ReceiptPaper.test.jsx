import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { receiptShop } from "@/applications/apparel/lib/receiptShop";
import { ReceiptPaper } from "./ReceiptDialog";

const base = {
  number: "A-7", date: "2026-11-20T10:00:00Z", cashier: "سارة", customerName: "عميل نقدي",
  items: [{ code: "S1", name: "شاي", qty: 2, price: 10, total: 20, color: "", size: "" }],
  pieces: 2, subTotal: 20, lineDiscount: 0, invoiceDiscount: 0, discount: 0, total: 20,
  paid: 20, change: 0, hasPayment: true, paymentLabel: "نقدي", note: "", currency: "EGP",
};
const draw = (over = {}, accountName = "") =>
  renderToStaticMarkup(createElement(ReceiptPaper, { receipt: { ...base, ...over }, accountName }));
const shopOf = (raw) => receiptShop(raw);

describe("ReceiptPaper shows what the owner set", () => {
  it("prints the shop's name, address, phone and tax number", () => {
    const html = draw({ shop: shopOf({ shop_name: "محل الأمل", address: "١٢ شارع النيل", phone: "0100", tax_id: "555" }) });
    expect(html).toContain("محل الأمل");
    expect(html).toContain("١٢ شارع النيل");
    expect(html).toContain("0100");
    expect(html).toContain("الرقم الضريبي: 555");
  });

  it("the shop's own name beats the signed-in account's", () => {
    const html = draw({ shop: shopOf({ shop_name: "محل الأمل" }) }, "اسم الحساب");
    expect(html).toContain("محل الأمل");
    expect(html).not.toContain("اسم الحساب");
  });

  it("falls back to the account's name only when the owner set none", () => {
    expect(draw({ shop: shopOf({}) }, "اسم الحساب")).toContain("اسم الحساب");
    expect(draw({ shop: undefined }, "اسم الحساب")).toContain("اسم الحساب");
  });

  it("promises the exchange period the owner chose, not a fixed one", () => {
    expect(draw({ shop: shopOf({ exchange_days: 30 }) })).toContain("الاستبدال خلال 30 يومًا");
    const seven = draw({ shop: shopOf({ exchange_days: 7 }) });
    expect(seven).toContain("الاستبدال خلال 7 يومًا");
    expect(seven).not.toContain("خلال 30");
    expect(seven).not.toContain("١٤");
  });

  it("promises no exchange at all when the shop gives none", () => {
    for (const shop of [shopOf({ exchange_days: 0 }), shopOf({}), undefined]) {
      expect(draw({ shop })).not.toContain("الاستبدال");
    }
  });

  it("prints the owner's header and footer text", () => {
    const html = draw({ shop: shopOf({ header_text: "أهلاً بكم", footer_text: "الإرجاع بالفاتورة فقط" }) });
    expect(html).toContain("أهلاً بكم");
    expect(html).toContain("الإرجاع بالفاتورة فقط");
  });

  it("keeps the thank-you line", () => {
    expect(draw({ shop: shopOf({}) })).toContain("شكرًا لتعاملكم معنا");
  });

  it("writes the order's currency, not a fixed one", () => {
    expect(draw({ currency: "EGP", shop: shopOf({}) })).toMatch(/20\.00 ج\.م/);
    const sar = draw({ currency: "SAR", shop: shopOf({}) });
    expect(sar).not.toMatch(/ج\.م/);
    expect(sar).toContain("20.00");
  });

  it("an order with no currency still prints an amount", () => {
    expect(draw({ currency: "", shop: shopOf({}) })).toMatch(/20\.00 ج\.م/);
  });

  it("leaves out a blank line instead of printing an empty label", () => {
    const html = draw({ shop: shopOf({ shop_name: "الأمل", tax_id: "   " }) });
    expect(html).not.toContain("الرقم الضريبي");
  });
});
