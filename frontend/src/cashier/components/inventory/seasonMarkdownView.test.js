import { describe, expect, it } from "vitest";
import {
  appliedMessage,
  belowCostWarning,
  canConfirm,
  canPreview,
  confirmLabel,
  floorNote,
  markdownColumns,
  markdownErrorMessage,
  previewSummary,
  priceChange,
  rowTone,
  unknownCostNote,
} from "./seasonMarkdownView";

const row = (over = {}) => ({ model: "قميص", colour: "أسود", size: "M", oldPrice: 100, newPrice: 80, unitCost: 60, costKnown: true, belowCost: false, atFloor: false, ...over });

describe("priceChange and rowTone", () => {
  it("shows old then new", () => {
    const t = priceChange(row());
    expect(t).toMatch(/100/);
    expect(t).toMatch(/80/);
    expect(t.indexOf("100")).toBeLessThan(t.indexOf("80"));
  });
  it("a size that would sell under cost is red, any other is plain", () => {
    expect(rowTone(row({ belowCost: true }))).toBe("loss");
    expect(rowTone(row({ belowCost: false }))).toBe("");
    expect(rowTone(undefined)).toBe("");
  });
});

describe("columns", () => {
  const cols = Object.fromEntries(markdownColumns().map((c) => [c.key, c]));
  it("has the five columns in reading order", () => {
    expect(markdownColumns().map((c) => c.key)).toEqual(["variant", "old", "new", "cost", "flag"]);
  });
  it("the new price is red when it is under cost, strong otherwise", () => {
    expect(cols.new.tone(row({ belowCost: true }))).toBe("loss");
    expect(cols.new.tone(row())).toBe("strong");
  });
  it("an unknown cost is a dash, never 0", () => {
    expect(cols.cost.text(row({ costKnown: false, unitCost: null }))).toBe("—");
    expect(cols.cost.text(row({ costKnown: false, unitCost: 0 }))).toBe("—");
    expect(cols.cost.text(row({ costKnown: true, unitCost: 60 }))).toMatch(/60/);
    expect(cols.cost.text(row({ costKnown: true, unitCost: 0 }))).not.toBe("—");
  });
  it("the flag column names under-cost first, then the floor, else nothing", () => {
    expect(cols.flag.text(row({ belowCost: true }))).toBe("تحت التكلفة");
    expect(cols.flag.text(row({ atFloor: true }))).toBe("أقل سعر");
    expect(cols.flag.text(row({ belowCost: true, atFloor: true }))).toBe("تحت التكلفة");
    expect(cols.flag.text(row())).toBe("");
    expect(cols.flag.tone(row({ belowCost: true }))).toBe("loss");
  });
});

describe("the sentences above the table", () => {
  it("the summary counts sizes and models, and adds the red count only when there is one", () => {
    expect(previewSummary({ variants: 5, products: 2, belowCost: 0 })).toBe("5 مقاس من 2 موديل هيتغيّر سعرهم");
    expect(previewSummary({ variants: 5, products: 2, belowCost: 3 })).toBe("5 مقاس من 2 موديل هيتغيّر سعرهم • 3 منهم هيتباع بأقل من التكلفة");
    expect(previewSummary({ variants: 0, products: 0 })).toBe("");
    expect(previewSummary(null)).toBe("");
  });
  it("the under-cost warning appears only when something goes under cost, and names how many", () => {
    expect(belowCostWarning({ belowCost: 0 })).toBeNull();
    expect(belowCostWarning(null)).toBeNull();
    const w = belowCostWarning({ belowCost: 4 });
    expect(w).toMatch(/4 مقاس/);
    expect(w).toMatch(/أقل من تكلفة الشراء/);
  });
  it("the unknown-cost note says it cannot tell, only when there are such sizes", () => {
    expect(unknownCostNote({ withoutCost: 0 })).toBeNull();
    expect(unknownCostNote({ withoutCost: 2 })).toMatch(/2 مقاس/);
  });
  it("the floor note appears only when a size was held at the lowest price", () => {
    expect(floorNote({ atFloor: 0 })).toBeNull();
    expect(floorNote({ atFloor: 1 })).toMatch(/1 مقاس/);
  });
});

describe("the buttons", () => {
  it("confirm names how many sizes it will change", () => {
    expect(confirmLabel({ totals: { variants: 12 } })).toBe("تأكيد التخفيض على 12 مقاس");
    expect(confirmLabel({ totals: { variants: 0 } })).toBe("تأكيد");
    expect(confirmLabel(null)).toBe("تأكيد");
  });
  it("preview needs a season and a valid percent and nothing running", () => {
    expect(canPreview({ season: "SS26", percentValid: true, busy: false })).toBe(true);
    expect(canPreview({ season: "", percentValid: true, busy: false })).toBe(false);
    expect(canPreview({ season: "   ", percentValid: true, busy: false })).toBe(false);
    expect(canPreview({ season: "SS26", percentValid: false, busy: false })).toBe(false);
    expect(canPreview({ season: "SS26", percentValid: true, busy: true })).toBe(false);
  });
  it("confirm needs a preview with a token and at least one size, and nothing running", () => {
    const p = { token: "t", totals: { variants: 3 } };
    expect(canConfirm({ preview: p, busy: false })).toBe(true);
    expect(canConfirm({ preview: { ...p, token: "" }, busy: false })).toBe(false);
    expect(canConfirm({ preview: { ...p, totals: { variants: 0 } }, busy: false })).toBe(false);
    expect(canConfirm({ preview: null, busy: false })).toBe(false);
    expect(canConfirm({ preview: p, busy: true })).toBe(false);
  });
});

describe("the messages", () => {
  it("each failure has its own words, and stale asks for a NEW preview", () => {
    const kinds = ["stale", "forbidden", "invalid", "offline", "failed"];
    const msgs = kinds.map(markdownErrorMessage);
    expect(new Set(msgs).size).toBe(kinds.length);
    expect(markdownErrorMessage("stale")).toMatch(/معاينة جديدة/);
    expect(markdownErrorMessage("forbidden")).toMatch(/لصاحب المحل/);
    expect(markdownErrorMessage("forbidden")).toMatch(/لو صاحب المحل سمح|سمح بكده/);
    expect(markdownErrorMessage("anything else")).toBe(markdownErrorMessage("failed"));
  });
  it("the success message says how many sizes changed", () => {
    expect(appliedMessage({ applied: 12 })).toBe("اتخفّض سعر 12 مقاس.");
    expect(appliedMessage(undefined)).toBe("اتخفّض سعر 0 مقاس.");
  });
});
