import { describe, expect, it } from "vitest";
import { MAX_COUNT, scanRefusal, scanToCount } from "./stocktakeScan";

const row = (id, name, sku, barcode, actual = null) => ({
  id,
  productName: name,
  sku,
  barcode,
  actual, // null = not counted yet
  stock: 5,
});

const rows = [
  row("v1", "قميص كتان", "SH-01-M", "2000001"),
  row("v2", "قميص كتان", "SH-01-L", "2000002", 3),
  row("v3", "بنطلون جينز", "JN-38", "3000001"),
];

describe("scanToCount", () => {
  it("counts an exact barcode into a line nobody has counted yet", () => {
    const out = scanToCount(rows, "2000001");
    expect(out.kind).toBe("hit");
    expect(out.row.id).toBe("v1");
    expect(out.wasCounted).toBe(false);
    expect(out.qty).toBe(1); // not null, and not "0 then 1"
  });

  it("adds one to what is already counted", () => {
    const out = scanToCount(rows, "2000002");
    expect(out).toMatchObject({ kind: "hit", qty: 4, wasCounted: true });
  });

  it("takes a code written with separators, Arabic digits or the wrong Arabic spelling", () => {
    expect(scanToCount(rows, " 2000-001 ").row.id).toBe("v1");
    expect(scanToCount(rows, "٢٠٠٠٠٠١").row.id).toBe("v1");
    expect(scanToCount(rows, "sh01m").row.id).toBe("v1"); // exact SKU, separators dropped
  });

  it("an exact code wins over a partial one", () => {
    const tricky = [row("a", "صنف", "SH-1", "111"), row("b", "صنف", "SH-11", "1112")];
    expect(scanToCount(tricky, "111").row.id).toBe("a");
    expect(scanToCount(tricky, "1112").row.id).toBe("b");
  });

  it("refuses a partial match that lands on more than one line", () => {
    const out = scanToCount(rows, "قميص");
    expect(out).toEqual({ kind: "ambiguous", count: 2 });
    expect(scanRefusal("ambiguous", "قميص")).toContain("أكثر من صنف");
  });

  it("says an item the shop has but this count does not include", () => {
    const known = [{ productName: "حزام جلد", sku: "BLT-1", barcode: "9999" }];
    const out = scanToCount(rows, "9999", { known });
    expect(out.kind).toBe("outside");
    expect(scanRefusal("outside", "9999")).toContain("مش داخل في هذا الجرد");
  });

  it("says a code that belongs to no item at all", () => {
    expect(scanToCount(rows, "555555").kind).toBe("none");
    expect(scanRefusal("none", "555555")).toContain("لا يوجد صنف");
  });

  it("ignores an empty scan and never refuses out loud", () => {
    expect(scanToCount(rows, "").kind).toBe("empty");
    expect(scanToCount(rows, "   ").kind).toBe("empty");
    expect(scanRefusal("hit", "2000001")).toBeNull();
  });

  it("stops at the maximum a line may hold", () => {
    const full = [row("v9", "صنف", "SKU-9", "777", MAX_COUNT)];
    expect(scanToCount(full, "777").qty).toBe(MAX_COUNT);
  });

  it("finds a line by its model name when only one line matches", () => {
    expect(scanToCount(rows, "جينز").row.id).toBe("v3");
  });
});
