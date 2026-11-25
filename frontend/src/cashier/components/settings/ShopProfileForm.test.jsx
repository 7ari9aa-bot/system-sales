import { describe, expect, it } from "vitest";
import { SHOP_PROFILE_KEYS } from "./ShopProfileForm";

// بيانات المحل كانت بتسأل عن الاسم والعنوان والهاتف والرقم الضريبي بس، والبريد والموقع والسجل
// التجاري والكود البريدي كانوا متاحين في محرك الإعدادات ومحدش بيرسمهم ولا بيقراهم. الاختبار ده
// بيثبّت إن الشاشة بقت بتعرضهم، وإن الإيصال بيقراهم (اختبار الباك إند المقابل).
describe("SHOP_PROFILE_KEYS", () => {
  it("covers the whole legal identity of the shop", () => {
    expect(SHOP_PROFILE_KEYS).toEqual([
      "business.trade_name",
      "business.legal_name",
      "business.address.line1",
      "business.address.city",
      "business.phone",
      "business.tax_id",
      "business.email",
      "business.website",
      "business.commercial_register",
      "business.address.postal_code",
    ]);
  });

  it("has no duplicates and never offers the capability switch as a shop detail", () => {
    expect(new Set(SHOP_PROFILE_KEYS).size).toBe(SHOP_PROFILE_KEYS.length);
    expect(SHOP_PROFILE_KEYS).not.toContain("business.vertical");
  });
});
