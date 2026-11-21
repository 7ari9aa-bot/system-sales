import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api";
import {
  costWarning,
  errorKind,
  estimateMark,
  isLoss,
  moneyCell,
  profitColumns,
  profitFootnote,
  profitTotalsRow,
  unitsText,
  variantLabel,
  profitErrorNotice,
} from "./profitView";

describe("money in a profit cell", () => {
  it("shows a profit with two decimals and the currency", () => {
    expect(moneyCell(125.5)).toBe("125.50 ج.م");
  });
  it("keeps the minus sign on a loss instead of showing a bare amount", () => {
    expect(moneyCell(-50)).toBe("-50.00 ج.م");
    expect(moneyCell(-0.05)).toBe("-0.05 ج.م");
  });
  it("never prints a signed zero, and treats a missing figure as zero", () => {
    expect(moneyCell(-0)).toBe("0.00 ج.م");
    expect(moneyCell(null)).toBe("0.00 ج.م");
    expect(moneyCell(undefined)).toBe("0.00 ج.م");
    expect(moneyCell("")).toBe("0.00 ج.م");
  });
  it("reads a negative string from the API as a loss too", () => {
    expect(moneyCell("-12.30")).toBe("-12.30 ج.م");
  });
});

describe("marking a loss", () => {
  it("is a loss only below zero: zero profit is not red", () => {
    expect(isLoss({ profit: -0.01 })).toBe(true);
    expect(isLoss({ profit: 0 })).toBe(false);
    expect(isLoss({ profit: 10 })).toBe(false);
    expect(isLoss({})).toBe(false);
    expect(isLoss(null)).toBe(false);
  });
});

describe("the variant cell", () => {
  it("puts the model first and the colour and size under it", () => {
    expect(variantLabel({ model: "جينز سليم", colour: "أزرق", size: "32" })).toEqual({
      title: "جينز سليم",
      detail: "أزرق / 32",
    });
  });
  it("leaves out a missing colour or size instead of printing a bare slash", () => {
    expect(variantLabel({ model: "قميص", colour: "", size: "M" })).toEqual({ title: "قميص", detail: "M" });
    expect(variantLabel({ model: "قميص", colour: "أبيض", size: null })).toEqual({ title: "قميص", detail: "أبيض" });
    expect(variantLabel({ model: "قميص" })).toEqual({ title: "قميص", detail: "" });
  });
  it("gives a nameless variant a readable label rather than an empty cell", () => {
    expect(variantLabel({ model: "", colour: "أحمر", size: "S" }).title).toBe("بند بلا اسم");
    expect(variantLabel(null).title).toBe("بند بلا اسم");
  });
  it("trims stray spaces so a blank model is treated as blank", () => {
    expect(variantLabel({ model: "   ", colour: "أزرق " }).title).toBe("بند بلا اسم");
    expect(variantLabel({ model: "قميص", colour: " أزرق " }).detail).toBe("أزرق");
  });
});

describe("the units cell", () => {
  it("shows the sold count alone when nothing came back", () => {
    expect(unitsText({ unitsSold: 12, unitsReturned: 0 })).toBe("12");
    expect(unitsText({ unitsSold: 12 })).toBe("12");
  });
  it("shows the returns next to the sold count when something did", () => {
    expect(unitsText({ unitsSold: 12, unitsReturned: 2 })).toBe("12 (مرتجع 2)");
  });
  it("reads string counts from the API", () => {
    expect(unitsText({ unitsSold: "7", unitsReturned: "1" })).toBe("7 (مرتجع 1)");
  });
});

describe("the estimate marker", () => {
  it("marks only a row whose cost came back as an estimate", () => {
    expect(estimateMark({ costIsEstimate: true })).toBe("≈");
    expect(estimateMark({ costIsEstimate: false })).toBe("");
    expect(estimateMark({})).toBe("");
  });
});

describe("the warning about a missing cost", () => {
  const complete = { costIsComplete: true, unitsWithoutCost: 0 };

  it("says nothing when every sold piece had a real cost", () => {
    expect(costWarning(complete, [{ unitsWithoutCost: 0 }])).toBeNull();
  });
  it("names the number of pieces that sold with no recorded cost", () => {
    const warning = costWarning({ costIsComplete: false, unitsWithoutCost: 3 }, []);
    expect(warning).toContain("3");
    expect(warning).toContain("ربح أعلى من الحقيقة");
  });
  it("counts the rows when the totals are missing", () => {
    expect(costWarning(null, [{ unitsWithoutCost: 2 }, { unitsWithoutCost: 1 }])).toContain("3");
  });
  it("never adds the totals and the rows together", () => {
    const warning = costWarning({ costIsComplete: false, unitsWithoutCost: 3 }, [
      { unitsWithoutCost: 2 },
      { unitsWithoutCost: 1 },
    ]);
    expect(warning).toContain("3");
    expect(warning).not.toContain("6");
  });
  it("still warns without a number when the server says the cost is incomplete", () => {
    const warning = costWarning({ costIsComplete: false, unitsWithoutCost: 0 }, []);
    expect(warning).toContain("مش كل القطع");
  });
  it("does not warn for a totals object that omits the flag but counts nothing missing", () => {
    expect(costWarning({}, [])).toBeNull();
    expect(costWarning(undefined, undefined)).toBeNull();
  });
  it("warns when only a row knows about a missing cost, even if the totals look complete", () => {
    expect(costWarning({ costIsComplete: true, unitsWithoutCost: 0 }, [{ unitsWithoutCost: 1 }])).toContain("1");
  });
});

describe("why the request failed", () => {
  it("tells no permission apart from a network failure", () => {
    expect(errorKind({ status: 403 })).toBe("forbidden");
    expect(errorKind({ status: 401 })).toBe("unauthorized");
    expect(errorKind({ status: 0 })).toBe("offline");
    expect(errorKind({ status: 500 })).toBe("failed");
    expect(errorKind(new Error("boom"))).toBe("failed");
    expect(errorKind(null)).toBe("failed");
  });

  it("reads a real permission denial as forbidden, not as a dead session", () => {
    // The exact error the API layer throws for `require_permission("pos:override")`: a genuine
    // role denial stays 403 (the api layer only maps token messages to 401), so the tab can say
    // "owner or manager only" instead of sending a cashier to the login screen.
    const denied = new ApiError("missing permission: pos:override", {
      status: 403,
      code: "permission_denied",
    });
    expect(denied.status).toBe(403);
    expect(errorKind(denied)).toBe("forbidden");
  });

  it("still tells a dead session apart from a role denial", () => {
    const expired = new ApiError("missing bearer token", { status: 401, code: "permission_denied" });
    expect(errorKind(expired)).toBe("unauthorized");
  });
});

describe("the totals row", () => {
  it("puts a label in the first cell and the server's totals in the rest", () => {
    const totals = {
      unitsSold: 40,
      revenue: 5000,
      cost: 3000,
      profit: 2000,
      margin: 40,
      unitsWithoutCost: 0,
      costIsComplete: true,
    };
    expect(profitTotalsRow(totals)).toEqual({
      variant: "الإجمالي",
      season: "",
      material: "",
      units: "40",
      revenue: "5,000.00 ج.م",
      cost: "3,000.00 ج.م",
      profit: "2,000.00 ج.م",
      margin: "40.0٪",
    });
  });
  it("shows a loss in the totals with its sign", () => {
    const row = profitTotalsRow({ unitsSold: 1, revenue: 100, cost: 150, profit: -50, margin: -50 });
    expect(row.profit).toBe("-50.00 ج.م");
    expect(row.margin).toBe("-50.0٪");
  });
  it("has no totals row when the server sent none", () => {
    expect(profitTotalsRow(null)).toBeNull();
    expect(profitTotalsRow(undefined)).toBeNull();
  });
});

describe("the footnote", () => {
  it("says what the figures are made of", () => {
    const note = profitFootnote({ profit: 1 }, []);
    expect(note).toContain("بعد الخصومات والمرتجعات");
    expect(note).not.toContain("≈");
  });
  it("explains the estimate marker only when a row carries it", () => {
    expect(profitFootnote({ profit: 1 }, [{ costIsEstimate: true }, { costIsEstimate: false }])).toContain("≈ 1 صنف");
    expect(profitFootnote({ profit: 1 }, [{ costIsEstimate: true }, { costIsEstimate: true }])).toContain("≈ 2");
  });
  it("is empty when there is nothing to explain", () => {
    expect(profitFootnote(null, [])).toBe("");
  });
});

describe("the columns the table is drawn from", () => {
  const col = (key) => profitColumns().find((c) => c.key === key);
  const loss = { profit: -30, margin: -12.5, revenue: 100, cost: 130, unitsSold: 2, model: "قميص", season: "" };

  it("keeps the column order and keys the totals row relies on", () => {
    expect(profitColumns().map((c) => c.key)).toEqual(["variant", "season", "material", "units", "revenue", "cost", "profit", "margin"]);
  });
  it("draws a loss in the loss tone and a profit in the strong tone", () => {
    expect(col("profit").tone(loss)).toBe("loss");
    expect(col("profit").tone({ profit: 30 })).toBe("strong");
    expect(col("profit").tone({ profit: 0 })).toBe("strong");
    expect(col("margin").tone(loss)).toBe("loss");
    expect(col("margin").tone({ margin: 0 })).toBe("");
  });
  it("prints the loss with its minus sign and the margin with the Arabic percent", () => {
    expect(col("profit").text(loss)).toBe("-30.00 ج.م");
    expect(col("margin").text(loss)).toBe("-12.5٪");
  });
  it("falls back to a dash for a missing season, never to an empty cell", () => {
    expect(col("season").text(loss)).toBe("—");
    expect(col("season").text({ season: "AW26" })).toBe("AW26");
  });
  it("prints the material next to the season, with the same dash for a product that has none", () => {
    expect(col("material").header).toBe("الخامة");
    expect(col("material").text(loss)).toBe("—");
    expect(col("material").text({ material: "قطن" })).toBe("قطن");
    expect(col("material").text({ material: null })).toBe("—");
    expect(col("material").tone()).toBe("muted");
  });
  it("carries the model as title and colour/size as the sub line, and the estimate mark", () => {
    expect(col("variant").text(loss)).toBe("قميص");
    expect(col("variant").sub({ model: "قميص", colour: "أزرق", size: "M" })).toBe("أزرق / M");
    expect(col("profit").mark({ costIsEstimate: true })).toBe("≈");
    expect(col("profit").mark({ costIsEstimate: false })).toBe("");
  });
});

describe("the totals row keys match the columns", () => {
  it("uses exactly the column keys, so ReportTable lays it under them", () => {
    const keys = Object.keys(profitTotalsRow({ profit: 1 })).sort();
    const cols = profitColumns().map((c) => c.key).sort();
    expect(keys).toEqual(cols);
  });
  it("shows a loss in the totals too", () => {
    const t = profitTotalsRow({ unitsSold: 3, revenue: 100, cost: 150, profit: -50, margin: -50 });
    expect(t.profit).toBe("-50.00 ج.م");
    expect(t.margin).toBe("-50.0٪");
    expect(t.units).toBe("3");
  });
});

describe("the notice shown instead of the table", () => {
  it("says nothing when nothing failed", () => {
    expect(profitErrorNotice(null)).toBeNull();
    expect(profitErrorNotice(undefined)).toBeNull();
  });
  it("tells a refused user the report is for the owner or manager, and offers no retry", () => {
    for (const status of [403, 401]) {
      const n = profitErrorNotice({ status });
      expect(n.tone).toBe("forbidden");
      expect(n.kind).toBe(status === 403 ? "forbidden" : "unauthorized");
      expect(n.message).toContain("لصاحب المحل أو المدير");
      expect(n.message).not.toContain("حاول مرة");
    }
  });
  it("a network failure and a server failure each say their own thing, and both are plain failures", () => {
    const offline = profitErrorNotice({ status: 0 });
    const failed = profitErrorNotice({ status: 500 });
    expect(offline.tone).toBe("failed");
    expect(failed.tone).toBe("failed");
    expect(offline.message).toContain("الاتصال");
    expect(failed.message).toContain("تعذّر تحميل تقرير الربح");
    expect(offline.message).not.toBe(failed.message);
  });
  it("an error with no status is a failed load, not a lost connection and not a refusal", () => {
    const n = profitErrorNotice(new Error("boom"));
    expect(n.kind).toBe("failed");
    expect(n.message).not.toContain("الاتصال");
    expect(n.message).not.toContain("لصاحب المحل");
  });
});
