import { describe, expect, it } from "vitest";
import {
  MAX_PERCENT,
  MIN_PERCENT,
  applyBody,
  markdownErrorKind,
  markdownRows,
  markdownTotals,
  percentText,
  previewBody,
  shapePreview,
} from "./seasonMarkdown";

describe("percentText: exact text, never a float", () => {
  it("passes a valid percent through as text", () => {
    expect(percentText("15")).toBe("15");
    expect(percentText("12.5")).toBe("12.5");
    expect(percentText("0.01")).toBe("0.01");
    expect(percentText("90")).toBe("90");
    expect(percentText(" 20 ")).toBe("20");
  });
  it("a number input is read as the text it prints", () => {
    expect(percentText(15)).toBe("15");
    expect(percentText(12.5)).toBe("12.5");
  });
  it("the bounds are 0.01 and 90, both included, nothing outside", () => {
    expect(MIN_PERCENT).toBe(0.01);
    expect(MAX_PERCENT).toBe(90);
    expect(percentText("0.009")).toBeNull();
    expect(percentText("0")).toBeNull();
    expect(percentText("0.00")).toBeNull();
    expect(percentText("90.01")).toBeNull();
    expect(percentText("91")).toBeNull();
    expect(percentText("100")).toBeNull();
  });
  it("more than two decimals is refused, because the server refuses it", () => {
    expect(percentText("12.345")).toBeNull();
    expect(percentText("1.005")).toBeNull();
  });
  it("reads Arabic-Indic digits and the Arabic decimal separator", () => {
    expect(percentText("٢٠")).toBe("20");
    expect(percentText("١٢٫٥")).toBe("12.5");
    expect(percentText("12,5")).toBe("12.5");
  });
  it("a trailing zero is dropped so the same percent is always the same request", () => {
    expect(percentText("15.0")).toBe("15");
    expect(percentText("15.50")).toBe("15.5");
    expect(percentText("20.00")).toBe("20");
  });
  it("garbage, empty and missing are null", () => {
    for (const bad of ["", "  ", "abc", "-5", "+5", "1e1", "NaN", "Infinity", "1.", ".5", "5%", null, undefined]) {
      expect(percentText(bad)).toBeNull();
    }
  });
});

describe("markdownRows", () => {
  const api = {
    variant_id: "v1", product_id: "p1", model: "قميص", colour: "أسود", size: "M",
    old_price: "100.00", new_price: "80.00", unit_cost: "60.00", cost_known: true, below_cost: false, at_floor: false,
  };
  it("maps a row", () => {
    expect(markdownRows([api])[0]).toEqual({
      id: "v1", productId: "p1", model: "قميص", colour: "أسود", size: "M",
      oldPrice: 100, newPrice: 80, unitCost: 60, costKnown: true, belowCost: false, atFloor: false,
    });
  });
  it("prices are exact to the cent", () => {
    const [r] = markdownRows([{ ...api, old_price: "19.99", new_price: "16.99" }]);
    expect(r.oldPrice).toBe(19.99);
    expect(r.newPrice).toBe(16.99);
  });
  it("an unknown cost stays null and never becomes below-cost", () => {
    const [r] = markdownRows([{ ...api, unit_cost: null, cost_known: false, below_cost: false }]);
    expect(r.unitCost).toBeNull();
    expect(r.costKnown).toBe(false);
    expect(r.belowCost).toBe(false);
  });
  it("flags are true only when the server says true", () => {
    const [r] = markdownRows([{ ...api, below_cost: "true", at_floor: 1, cost_known: "yes" }]);
    expect(r.belowCost).toBe(false);
    expect(r.atFloor).toBe(false);
    expect(r.costKnown).toBe(false);
    expect(markdownRows([{ ...api, below_cost: true, at_floor: true }])[0]).toMatchObject({ belowCost: true, atFloor: true });
  });
  it("copes with no rows", () => {
    expect(markdownRows()).toEqual([]);
    expect(markdownRows(null)).toEqual([]);
  });
});

describe("markdownTotals and shapePreview", () => {
  it("maps the totals, missing ones are zero", () => {
    expect(markdownTotals({ variants: 3, products: 2, below_cost: 1, at_floor: 1, without_cost: 1 })).toEqual({
      variants: 3, products: 2, belowCost: 1, atFloor: 1, withoutCost: 1,
    });
    expect(markdownTotals(undefined)).toEqual({ variants: 0, products: 0, belowCost: 0, atFloor: 0, withoutCost: 0 });
  });
  it("keeps the token exactly as the server sent it", () => {
    const t = "a".repeat(64);
    expect(shapePreview({ season: "SS26", percent: "20", token: t, rows: [], totals: {} }).token).toBe(t);
  });
  it("a missing or non-text token becomes empty, so confirm can never be armed by it", () => {
    expect(shapePreview({}).token).toBe("");
    expect(shapePreview({ token: 5 }).token).toBe("");
    expect(shapePreview(undefined).rows).toEqual([]);
  });
});

describe("the request bodies", () => {
  it("preview sends the trimmed season and the percent as text", () => {
    expect(previewBody({ season: " SS26 ", percent: "12.5" })).toEqual({ season: "SS26", percent: "12.5" });
  });
  it("a blank brand is left out, a chosen one is sent", () => {
    expect("brand_id" in previewBody({ season: "SS26", percent: "20", brandId: "" })).toBe(false);
    expect(previewBody({ season: "SS26", percent: "20", brandId: "b1" }).brand_id).toBe("b1");
  });
  it("an invalid percent becomes null in the body, not a number", () => {
    expect(previewBody({ season: "SS26", percent: "abc" }).percent).toBeNull();
  });
  it("apply repeats what the preview was made with and adds its token", () => {
    const p = { season: "SS26", percent: "20", token: "tok", rows: [], totals: {} };
    expect(applyBody(p)).toEqual({ season: "SS26", percent: "20", token: "tok" });
    expect(applyBody(p, "b1")).toEqual({ season: "SS26", percent: "20", token: "tok", brand_id: "b1" });
  });
});

describe("markdownErrorKind: a 409 means preview again, not retry", () => {
  it("separates every way a request can fail", () => {
    expect(markdownErrorKind({ status: 409 })).toBe("stale");
    expect(markdownErrorKind({ status: 403 })).toBe("forbidden");
    expect(markdownErrorKind({ status: 401 })).toBe("forbidden");
    expect(markdownErrorKind({ status: 400 })).toBe("invalid");
    expect(markdownErrorKind({ status: 422 })).toBe("invalid");
    expect(markdownErrorKind({ status: 0 })).toBe("offline");
    expect(markdownErrorKind({ status: 500 })).toBe("failed");
    expect(markdownErrorKind(undefined)).toBe("failed");
  });
});
