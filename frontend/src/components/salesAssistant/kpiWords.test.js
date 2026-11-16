import { describe, expect, it } from "vitest";
import ar from "@/lib/i18n/ar.js";
import en from "@/lib/i18n/en.js";
import { metricLabel, unitLabel, windowLabel } from "./kpiWords";

const tr = (dict) => (key, vars) => {
  let s = dict[key] ?? key;
  if (vars) s = s.replace(/\{(\w+)\}/g, (_, k) => String(vars[k]));
  return s;
};
const tAr = tr(ar);
const tEn = tr(en);
const KNOWN = ["orders_placed", "delivered_revenue", "shipped_orders", "collected_revenue", "refund_amount", "net_revenue", "aov"];

describe("metricLabel", () => {
  it("gives every known metric a plain word in both languages, never the internal name", () => {
    for (const m of KNOWN) {
      for (const t of [tAr, tEn]) {
        const w = metricLabel(m, t);
        expect(w).toBeTruthy();
        expect(w).not.toMatch(/_/);
        expect(w).not.toBe(m);
        expect(w).not.toMatch(/^kpi\./); // a missing translation would show its key
      }
    }
  });
  it("every known metric is really in the table: Arabic in Arabic, never the English fallback", () => {
    for (const m of KNOWN) {
      expect(metricLabel(m, tAr), m).toMatch(/[\u0600-\u06FF]/);
      expect(metricLabel(m, tAr), m).not.toBe(m.replace(/_/g, " "));
      expect(metricLabel(m, tEn), m).not.toBe(m.replace(/_/g, " "));
    }
  });
  it("uses the same shop words as the written answer (plain_words.KNOWN)", () => {
    expect(metricLabel("delivered_revenue", tAr)).toBe("المبيعات المسلَّمة");
    expect(metricLabel("orders_placed", tAr)).toBe("عدد الأوردرات");
    expect(metricLabel("collected_revenue", tAr)).toBe("الفلوس المتحصّلة");
  });
  it("never leaks an unknown identifier: underscores become spaces", () => {
    expect(metricLabel("new_metric_x", tAr)).toBe("new metric x");
  });
  it("copes with empty and non-string input", () => {
    for (const bad of ["", "  ", null, undefined, 5, {}]) expect(metricLabel(bad, tAr)).toBe("");
  });
});

describe("unitLabel", () => {
  it("drops the internal unit words the label already covers", () => {
    for (const u of ["money", "count", "orders", "Money", " COUNT "]) expect(unitLabel(u)).toBe("");
  });
  it("keeps a real currency", () => {
    expect(unitLabel("EGP")).toBe("EGP");
    expect(unitLabel(" SAR ")).toBe("SAR");
  });
  it("copes with empty input", () => {
    for (const bad of ["", null, undefined, 3]) expect(unitLabel(bad)).toBe("");
  });
});

describe("windowLabel", () => {
  it("turns 15d into a number of days in the owner's language", () => {
    expect(windowLabel("15d", tAr)).toBe("15 يوم");
    expect(windowLabel("46d", tEn)).toBe("46 days");
  });
  it("has its own words for 0 and 1 day", () => {
    expect(windowLabel("0d", tAr)).toBe("اليوم");
    expect(windowLabel("1d", tAr)).toBe("يوم واحد");
    expect(windowLabel("1d", tEn)).toBe("1 day");
  });
  it("leaves anything else as it came, and an empty one empty", () => {
    expect(windowLabel("2026-11-01..2026-11-15", tAr)).toBe("2026-11-01..2026-11-15");
    expect(windowLabel("", tAr)).toBe("");
    expect(windowLabel(null, tAr)).toBe("");
  });
});
