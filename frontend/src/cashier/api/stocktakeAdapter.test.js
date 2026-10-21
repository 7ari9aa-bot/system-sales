import { describe, expect, it } from "vitest";
import { changedCounts, diffOf, parseCount, sheetFromApi, sheetTotals, stocktakeErrorMessage } from "./stocktakeAdapter";

const stock = [
  { id: "a", productName: "قميص", sku: "S-A", color: "أسود", size: "L" },
  { id: "b", productName: "بنطلون", sku: "S-B", color: "أزرق", size: "M" },
];
const detail = {
  id: "st1",
  status: "OPEN",
  note: "جرد",
  closed_at: null,
  lines: [
    { variant_id: "a", expected_qty: 10, counted_qty: null, current_qty: 8, applied_delta: null },
    { variant_id: "b", expected_qty: 4, counted_qty: 4, current_qty: 4, applied_delta: null },
    { variant_id: "zz", expected_qty: 1, counted_qty: 0, current_qty: 1, applied_delta: null },
  ],
};

describe("parseCount", () => {
  it("an empty box is NOT counted (null), never zero", () => {
    expect(parseCount("")).toBeNull();
    expect(parseCount("   ")).toBeNull();
    expect(parseCount(undefined)).toBeNull();
  });
  it("a typed zero IS a real zero", () => expect(parseCount("0")).toBe(0));
  it("takes whole non-negative numbers", () => {
    expect(parseCount("7")).toBe(7);
    expect(parseCount(" 12 ")).toBe(12);
  });
  it.each(["-1", "2.5", "1e3", "abc", "٣", "1,000", "+5"])("rejects %s", (bad) => {
    expect(() => parseCount(bad)).toThrow(RangeError);
  });
  it("rejects a count above the server ceiling", () => {
    expect(parseCount("1000000")).toBe(1_000_000);
    expect(() => parseCount("1000001")).toThrow(RangeError);
  });
});

describe("sheetFromApi", () => {
  const sheet = sheetFromApi(detail, stock);
  it("names the lines from the stock rows and keeps an unknown variant visible", () => {
    expect(sheet.rows.map((r) => r.productName)).toEqual(["قميص", "بنطلون", "صنف غير معروف"]);
  });
  it("keeps 'not counted' as null and a counted zero as 0", () => {
    expect(sheet.rows[0].actual).toBeNull();
    expect(sheet.rows[2].actual).toBe(0);
  });
  it("book is the snapshot; drift is how far the live balance moved since", () => {
    expect(sheet.rows[0]).toMatchObject({ stock: 10, current: 8, drift: -2 });
  });
});

describe("difference", () => {
  it("is counted - snapshot, and null while not counted", () => {
    const [a, b, z] = sheetFromApi(detail, stock).rows;
    expect(diffOf(a)).toBeNull();
    expect(diffOf(b)).toBe(0);
    expect(diffOf(z)).toBe(-1);
  });
  it("a sale during the count (drift) is NOT a missing item", () => {
    const row = sheetFromApi(
      { lines: [{ variant_id: "a", expected_qty: 10, counted_qty: 8, current_qty: 8 }] },
      stock,
    ).rows[0];
    expect(row.drift).toBe(-2);
    expect(diffOf(row)).toBe(-2); // counted 8 against the snapshot 10 is a real shortage of 2
  });
});

describe("sheetTotals", () => {
  it("counts only counted lines and sums the net difference", () => {
    const rows = sheetFromApi(detail, stock).rows;
    expect(sheetTotals(rows)).toEqual({ total: 3, counted: 2, notCounted: 1, withDiff: 1, net: -1 });
  });
  it("an untouched sheet has no difference at all", () => {
    const rows = sheetFromApi({ lines: [{ variant_id: "a", expected_qty: 9, counted_qty: null, current_qty: 9 }] }, stock).rows;
    expect(sheetTotals(rows)).toEqual({ total: 1, counted: 0, notCounted: 1, withDiff: 0, net: 0 });
  });
});

describe("changedCounts", () => {
  const saved = sheetFromApi(detail, stock);
  it("sends nothing when nothing changed", () => expect(changedCounts(saved.rows, saved)).toEqual([]));
  it("sends only the edited lines, including clearing one back to null", () => {
    const rows = saved.rows.map((r) =>
      r.id === "a" ? { ...r, actual: 7 } : r.id === "b" ? { ...r, actual: null } : r,
    );
    expect(changedCounts(rows, saved)).toEqual([
      { variant_id: "a", counted_qty: 7 },
      { variant_id: "b", counted_qty: null },
    ]);
  });
});

describe("stocktakeErrorMessage", () => {
  it("tells a non-manager that approval is the manager's", () => {
    expect(stocktakeErrorMessage({ status: 403 }, "approve")).toMatch(/المدير/);
  });
  it("tells a second open count apart from a closed one", () => {
    expect(stocktakeErrorMessage({ status: 409 }, "open")).toMatch(/مفتوح/);
    expect(stocktakeErrorMessage({ status: 409 }, "approve")).toMatch(/أُغلق/);
  });
  it("never leaks a raw status for an unknown failure", () => {
    expect(stocktakeErrorMessage({ status: 500 })).not.toMatch(/500/);
    expect(stocktakeErrorMessage(undefined)).toBeTruthy();
  });
});
