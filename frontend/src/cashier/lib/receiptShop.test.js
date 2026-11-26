import { describe, expect, it } from "vitest";
import { currencyLabel, receiptFooterLines, receiptHeaderLines, receiptShop } from "./receiptShop";

const full = {
  shop_name: "  محل الأمل ", address: "١٢ شارع النيل, القاهرة", phone: "0100", tax_id: "123",
  paper_mm: 58, show_logo: true, header_text: " أهلاً ", footer_text: "الإرجاع بالفاتورة",
  copies: 2, show_tax_detail: true, exchange_days: 30, return_days: 14,
};

describe("receiptShop", () => {
  it("carries every field the server sent, trimmed", () => {
    expect(receiptShop(full)).toEqual({
      name: "محل الأمل", address: "١٢ شارع النيل, القاهرة", phone: "0100", taxId: "123",
      paperMm: 58, showLogo: true, headerText: "أهلاً", footerText: "الإرجاع بالفاتورة",
      copies: 2, showTaxDetail: true, exchangeDays: 30, returnDays: 14,
    });
  });

  it.each([undefined, null, "x", 5, []])("a reply with no shop block (%s) gives safe defaults", (raw) => {
    expect(receiptShop(raw)).toEqual({
      name: "", address: "", phone: "", taxId: "", paperMm: 80, showLogo: false,
      headerText: "", footerText: "", copies: 1, showTaxDetail: false, exchangeDays: 0, returnDays: 0,
    });
  });

  it("only the two rolls a till takes are accepted for paper", () => {
    expect(receiptShop({ paper_mm: 58 }).paperMm).toBe(58);
    expect(receiptShop({ paper_mm: 80 }).paperMm).toBe(80);
    for (const bad of [46, 210, "80", null, NaN]) expect(receiptShop({ paper_mm: bad }).paperMm).toBe(80);
  });

  it("keeps copies and the exchange period inside what a shop can mean", () => {
    expect(receiptShop({ copies: 0 }).copies).toBe(1);
    expect(receiptShop({ copies: 99 }).copies).toBe(5);
    expect(receiptShop({ copies: 2.9 }).copies).toBe(2);
    expect(receiptShop({ copies: "3" }).copies).toBe(1);
    expect(receiptShop({ exchange_days: -3 }).exchangeDays).toBe(0);
    expect(receiptShop({ exchange_days: 9999 }).exchangeDays).toBe(365);
    expect(receiptShop({ exchange_days: Infinity }).exchangeDays).toBe(0);
    expect(receiptShop({ return_days: -1 }).returnDays).toBe(0);
    expect(receiptShop({ return_days: 14 }).returnDays).toBe(14);
    expect(receiptShop({ return_days: 4000 }).returnDays).toBe(365);
  });

  it("a switch is on only when the server said true", () => {
    for (const v of [1, "true", "yes", null, undefined]) {
      expect(receiptShop({ show_logo: v, show_tax_detail: v })).toMatchObject({ showLogo: false, showTaxDetail: false });
    }
  });
});

describe("receiptFooterLines", () => {
  it("prints the exchange period the owner set, not a fixed one", () => {
    expect(receiptFooterLines(receiptShop({ exchange_days: 30 }))).toEqual(["الاستبدال خلال 30 يومًا بشرط وجود الفاتورة"]);
    expect(receiptFooterLines(receiptShop({ exchange_days: 7 }))).toEqual(["الاستبدال خلال 7 يومًا بشرط وجود الفاتورة"]);
  });

  it("says one day in the singular", () => {
    expect(receiptFooterLines(receiptShop({ exchange_days: 1 }))).toEqual(["الاستبدال خلال يوم واحد بشرط وجود الفاتورة"]);
  });

  it("promises nothing when the shop does not allow exchanges", () => {
    expect(receiptFooterLines(receiptShop({ exchange_days: 0 }))).toEqual([]);
    expect(receiptFooterLines(receiptShop({}))).toEqual([]);
  });

  it("puts the owner's own footer first, then the exchange and return promises", () => {
    expect(receiptFooterLines(receiptShop(full))).toEqual([
      "الإرجاع بالفاتورة",
      "الاستبدال خلال 30 يومًا بشرط وجود الفاتورة",
      "المرتجع خلال 14 يومًا بشرط وجود الفاتورة",
    ]);
  });

  it("prints no return promise when the shop allows no returns", () => {
    expect(receiptFooterLines(receiptShop({ return_days: 0, exchange_days: 7 }))).toEqual([
      "الاستبدال خلال 7 يومًا بشرط وجود الفاتورة",
    ]);
    expect(receiptFooterLines(receiptShop({ return_days: 1 }))).toEqual([
      "المرتجع خلال يوم واحد بشرط وجود الفاتورة",
    ]);
  });
});

describe("receiptHeaderLines", () => {
  it("lists what the owner filled in, in reading order", () => {
    expect(receiptHeaderLines(receiptShop(full))).toEqual(["أهلاً", "١٢ شارع النيل, القاهرة", "0100", "الرقم الضريبي: 123"]);
  });

  it("leaves out what is blank, never a label with nothing after it", () => {
    expect(receiptHeaderLines(receiptShop({ phone: "0100" }))).toEqual(["0100"]);
    expect(receiptHeaderLines(receiptShop({ tax_id: "  " }))).toEqual([]);
  });
});

describe("currencyLabel", () => {
  it("writes the sign the browser uses in Arabic", () => {
    expect(currencyLabel("EGP")).toMatch(/ج\.م/);
    expect(currencyLabel("egp")).toBe(currencyLabel("EGP"));
    expect(currencyLabel(" EGP ")).toBe(currencyLabel("EGP"));
  });

  it("covers a currency this code never heard of, without a table", () => {
    expect(currencyLabel("SAR")).toBeTruthy();
    expect(currencyLabel("SAR")).not.toBe(currencyLabel("EGP"));
  });

  it("prints a code the browser cannot name as the code itself", () => {
    expect(currencyLabel("ZZZ")).toBe("ZZZ");
  });

  it.each([undefined, null, "", "E", "EGPX", "e1p", 5, "ج.م"])("gives nothing for %s, so the caller falls back", (v) => {
    expect(currencyLabel(v)).toBe("");
  });
});
