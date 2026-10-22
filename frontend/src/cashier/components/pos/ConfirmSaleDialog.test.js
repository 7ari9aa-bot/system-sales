import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ConfirmSaleBody } from "./ConfirmSaleDialog";

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
