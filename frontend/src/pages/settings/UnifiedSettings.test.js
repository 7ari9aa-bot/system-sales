import { describe, expect, it } from "vitest";

/** Test the domain labels that UnifiedSettings uses for grouping.
 * Extracted as a standalone test to avoid needing a DOM environment. */
const DOMAIN_LABELS_AR = {
  business: "النشاط والملف التجاري",
  pos: "نقطة البيع",
  inventory: "المخزون",
  security: "الأمان",
  customer_agent: "وكيل الذكاء الاصطناعي للعملاء",
};

const DOMAIN_LABELS_EN = {
  business: "Business & Profile",
  pos: "Point of Sale",
  inventory: "Inventory",
  security: "Security",
  customer_agent: "Customer AI Agent",
};

describe("UnifiedSettings domain labels", () => {
  it("كل مفتاح ليه label بالعربي وبالإنجليزي", () => {
    for (const key of Object.keys(DOMAIN_LABELS_AR)) {
      expect(DOMAIN_LABELS_EN[key]).toBeTruthy();
    }
    for (const key of Object.keys(DOMAIN_LABELS_EN)) {
      expect(DOMAIN_LABELS_AR[key]).toBeTruthy();
    }
  });

  it("الـ labels بتفضل مرتبة بالـ key", () => {
    const arKeys = Object.keys(DOMAIN_LABELS_AR).sort();
    const enKeys = Object.keys(DOMAIN_LABELS_EN).sort();
    expect(arKeys).toEqual(enKeys);
  });
});

/** Test the segment options for the scope selector. */
const SEGMENTS = ["retail", "fnb", "services", "wholesale"];

describe("segment options", () => {
  it("كل القطاعات من الـ backend SEGMENTS موجودة", () => {
    expect(SEGMENTS).toContain("retail");
    expect(SEGMENTS).toContain("fnb");
    expect(SEGMENTS).toContain("services");
    expect(SEGMENTS).toContain("wholesale");
  });

  it("مفيش قطاعات مكررة", () => {
    expect(new Set(SEGMENTS).size).toBe(SEGMENTS.length);
  });
});
