import { describe, expect, it } from "vitest";
import {
  costGapWarning,
  deadStockColumns,
  deadStockErrorNotice,
  deadStockHeader,
  deadStockTotalsRow,
  sinceLabel,
  valueLabel,
} from "./deadStockView";

const row = (over = {}) => ({ model: "قميص", colour: "أسود", size: "M", season: "SS26", unitsOnHand: 4, daysSinceSale: 90, costKnown: true, value: 50, ...over });

describe("sinceLabel", () => {
  it("days since the last sale", () => {
    expect(sinceLabel(row({ daysSinceSale: 90 }))).toBe("90 يوم");
    expect(sinceLabel(row({ daysSinceSale: 0 }))).toBe("0 يوم");
  });
  it("a size that never sold says so, and a real 0 is not 'never'", () => {
    expect(sinceLabel(row({ daysSinceSale: null }))).toBe("ما اتباعش");
    expect(sinceLabel(row({ daysSinceSale: undefined }))).toBe("ما اتباعش");
    expect(sinceLabel(row({ daysSinceSale: 0 }))).not.toBe("ما اتباعش");
  });
});

describe("valueLabel: an unknown cost is a dash, never 0", () => {
  it("a known cost prints the money", () => {
    expect(valueLabel(row({ costKnown: true, value: 50 }))).toMatch(/50/);
  });
  it("an unknown cost is a dash", () => {
    expect(valueLabel(row({ costKnown: false, value: null }))).toBe("—");
  });
  it("a row flagged unknown is a dash even if a figure slipped in", () => {
    expect(valueLabel(row({ costKnown: false, value: 0 }))).toBe("—");
  });
  it("a known cost with no figure is a dash, and a known zero is a zero", () => {
    expect(valueLabel(row({ costKnown: true, value: null }))).toBe("—");
    expect(valueLabel(row({ costKnown: true, value: 0 }))).not.toBe("—");
  });
});

describe("columns", () => {
  const cols = Object.fromEntries(deadStockColumns().map((c) => [c.key, c]));
  it("has the five columns in reading order", () => {
    expect(deadStockColumns().map((c) => c.key)).toEqual(["variant", "season", "onHand", "since", "value"]);
  });
  it("the variant cell is the model with colour and size under it", () => {
    expect(cols.variant.text(row())).toBe("قميص");
    expect(cols.variant.sub(row())).toBe("أسود / M");
  });
  it("never sold is red, sold long ago is muted", () => {
    expect(cols.since.tone(row({ daysSinceSale: null }))).toBe("loss");
    expect(cols.since.tone(row({ daysSinceSale: 90 }))).toBe("muted");
    expect(cols.since.tone(row({ daysSinceSale: 0 }))).toBe("muted");
  });
  it("an unknown cost is red, a known one is strong", () => {
    expect(cols.value.tone(row({ costKnown: false }))).toBe("loss");
    expect(cols.value.tone(row({ costKnown: true }))).toBe("strong");
  });
});

describe("the totals row", () => {
  it("uses the same keys as the columns", () => {
    const t = deadStockTotalsRow({ unitsOnHand: 9, value: 90 });
    expect(t.variant).toBe("الإجمالي");
    expect(t.onHand).toBe("9");
    for (const c of deadStockColumns()) expect(c.key in t).toBe(true);
  });
  it("is null when there are no totals", () => {
    expect(deadStockTotalsRow(null)).toBeNull();
  });
});

describe("costGapWarning", () => {
  it("a single size without a cost is already a warning, and it says one, not none", () => {
    const w = costGapWarning({ withoutCost: 1, costIsComplete: false });
    expect(w).not.toBeNull();
    expect(w).toMatch(/1 مقاس/);
    expect(w).toMatch(/ناقصة/);
  });

  it("none when the server says every cost is known and none are missing", () => {
    expect(costGapWarning({ withoutCost: 0, costIsComplete: true })).toBeNull();
  });
  it("names how many sizes are missing a cost", () => {
    const w = costGapWarning({ withoutCost: 3, costIsComplete: false });
    expect(w).toMatch(/3 مقاس/);
    expect(w).toMatch(/ناقصة/);
  });
  it("a missing flag is not a promise: it still warns", () => {
    expect(costGapWarning({ withoutCost: 0, costIsComplete: false })).toMatch(/ممكن تكون ناقصة/);
    expect(costGapWarning({ withoutCost: 0 })).not.toBeNull();
  });
  it("a count of missing costs warns even if the flag says complete", () => {
    expect(costGapWarning({ withoutCost: 2, costIsComplete: true })).toMatch(/2 مقاس/);
  });
  it("no totals, no warning", () => {
    expect(costGapWarning(null)).toBeNull();
  });
});

describe("the header and the notice", () => {
  it("the header names the window the server used", () => {
    expect(deadStockHeader(60)).toMatch(/60 يوم/);
    expect(deadStockHeader(null)).toBeNull();
    expect(deadStockHeader(0)).toBeNull();
  });
  it("no error, no notice; no permission names who can open it", () => {
    expect(deadStockErrorNotice(null, "failed")).toBeNull();
    const n = deadStockErrorNotice({ status: 403 }, "forbidden");
    expect(n.tone).toBe("forbidden");
    expect(n.message).toMatch(/لصاحب المتجر/);
    expect(n.message).toMatch(/لو صاحب المتجر سمح/);
    expect(deadStockErrorNotice({ status: 401 }, "unauthorized").tone).toBe("forbidden");
  });
  it("offline and failed are different messages", () => {
    const off = deadStockErrorNotice({ status: 0 }, "offline");
    const bad = deadStockErrorNotice({ status: 500 }, "failed");
    expect(off.message).toMatch(/الاتصال/);
    expect(bad.message).toMatch(/المخزون الراكد/);
    expect(off.message).not.toBe(bad.message);
  });
});
