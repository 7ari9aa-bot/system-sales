import { describe, expect, it } from "vitest";
import ar from "@/lib/i18n/ar.js";
import en from "@/lib/i18n/en.js";
import { readFileSync } from "node:fs";
import { KNOWN_METRICS, metricLabel, noticeText, unitLabel, windowLabel } from "./kpiWords";

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

describe("every metric the server can send has a plain word", () => {
  // The server's own list, read from the file that builds the cards. A new metric added there
  // without a word here fails this test, instead of showing the owner an internal name.
  const SERVER = readFileSync("../backend/app/applications/apparel/modules/ai/agents/sales_intelligence/tools.py", "utf8");
  const sent = [...SERVER.matchAll(/^\s+\("([a-z_]+)", [^\n]*"(?:money|count)", \{\}\),?$/gm)].map((m) => m[1]);
  it("finds the metrics in the server file (guards the guard)", () => {
    expect(sent.length).toBeGreaterThan(20);
    expect(sent).toContain("pos_sales_total");
  });
  it("has a real Arabic and English word for each, never the English fallback", () => {
    for (const m of new Set(sent)) {
      expect(KNOWN_METRICS, m).toContain(m);
      expect(metricLabel(m, tAr), m).toMatch(/[\u0600-\u06FF]/);
      expect(metricLabel(m, tEn), m).not.toMatch(/_|^kpi\./);
    }
  });
});

describe("noticeText", () => {
  it("turns the technical line from production into a plain sentence", () => {
    const t = noticeText("safe response: si_response_invalid", tAr);
    expect(t).not.toMatch(/si_response|safe response/);
    expect(t).toMatch(/[\u0600-\u06FF]/);
  });
  it("covers every reason the server can send, in both languages", () => {
    for (const r of ["si_response_invalid", "unsourced_claim", "unverified_commercial_claim", "injection_risk", "cross_tenant_request", "handover", "unknown_agent_kind"]) {
      for (const t of [tAr, tEn]) expect(noticeText(`safe response: ${r}`, t), r).not.toMatch(/_|^notice\./);
    }
    for (const q of ["partial", "immature", "stale", "insufficient", "conflicting"]) {
      for (const t of [tAr, tEn]) expect(noticeText(`data quality: ${q}`, t), q).not.toMatch(/_|^notice\./);
    }
  });
  it("every known reason gets its OWN sentence, not the general one for unknown reasons", () => {
    const generalSafe = noticeText("safe response: nothing_known", tAr);
    for (const r of ["si_response_invalid", "unsourced_claim", "unverified_commercial_claim", "injection_risk", "cross_tenant_request", "handover", "unknown_agent_kind"]) {
      expect(noticeText(`safe response: ${r}`, tAr), r).not.toBe(generalSafe);
      expect(noticeText(`safe response: ${r}`, tEn), r).not.toBe(noticeText("safe response: nothing_known", tEn));
    }
    const generalQ = noticeText("data quality: nothing_known", tAr);
    for (const q of ["partial", "immature", "stale", "insufficient", "conflicting"]) {
      expect(noticeText(`data quality: ${q}`, tAr), q).not.toBe(generalQ);
      expect(noticeText(`data quality: ${q}`, tEn), q).not.toBe(noticeText("data quality: nothing_known", tEn));
    }
  });
  it("reads the line whatever its letter case", () => {
    expect(noticeText("Safe Response: SI_RESPONSE_INVALID", tAr)).toBe(noticeText("safe response: si_response_invalid", tAr));
    expect(noticeText("Data Quality: PARTIAL", tAr)).toBe(noticeText("data quality: partial", tAr));
  });
  it("never shows an unknown reason raw", () => {
    expect(noticeText("safe response: brand_new_reason", tAr)).not.toMatch(/brand_new_reason/);
    expect(noticeText("data quality: weird_state", tEn)).not.toMatch(/weird_state/);
  });
  it("leaves an ordinary notice as it is, and copes with empty input", () => {
    expect(noticeText("الفترة قصيرة", tAr)).toBe("الفترة قصيرة");
    for (const bad of ["", "  ", null, undefined, 4]) expect(noticeText(bad, tAr)).toBe("");
  });
});
