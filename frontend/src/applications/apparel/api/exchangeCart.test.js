import { describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { posApi } from "./posApi";
import { addReplacement, clampReplacementQty, previewTotal, removeReplacement, setReplacementQty } from "./exchangeCart";

vi.mock("@/lib/api", () => ({ api: vi.fn(async () => ({ grand_total: "700.00" })) }));

const v = (over = {}) => ({ id: "n1", sku: "S1", barcode: "b1", productName: "قميص", color: "red", size: "M", stock: 2, sellPrice: 350, ...over });

describe("addReplacement", () => {
  it("adds a new line with qty 1", () => {
    const r = addReplacement([], v());
    expect(r.ok).toBe(true);
    expect(r.lines).toHaveLength(1);
    expect(r.lines[0]).toMatchObject({ variantId: "n1", qty: 1, price: 350, code: "S1" });
  });
  it("same variant again raises qty, never duplicates the row", () => {
    const r = addReplacement(addReplacement([], v()).lines, v());
    expect(r.lines).toHaveLength(1);
    expect(r.lines[0].qty).toBe(2);
  });
  it("stops at the available stock and says so", () => {
    const full = addReplacement(addReplacement([], v()).lines, v()).lines;
    const r = addReplacement(full, v());
    expect(r.ok).toBe(false);
    expect(r.reason).toMatch(/المتاح 2/);
    expect(r.lines).toBe(full);
  });
  it("refuses an out-of-stock variant", () => expect(addReplacement([], v({ stock: 0 }))).toMatchObject({ ok: false, reason: "نافد من المخزون" }));
});

describe("quantity", () => {
  it("clamps to 1..stock and survives junk", () => {
    const l = { stock: 3 };
    expect([clampReplacementQty(l, 99), clampReplacementQty(l, 0), clampReplacementQty(l, "x"), clampReplacementQty(l, 2.9)]).toEqual([3, 1, 1, 2]);
  });
  it("setReplacementQty only touches its line", () => {
    const lines = [{ lineId: "a", stock: 5, qty: 1 }, { lineId: "b", stock: 5, qty: 1 }];
    expect(setReplacementQty(lines, "a", 4).map((l) => l.qty)).toEqual([4, 1]);
  });
  it("removeReplacement", () => expect(removeReplacement([{ lineId: "a" }, { lineId: "b" }], "a")).toEqual([{ lineId: "b" }]));
});

describe("previewTotal", () => {
  it("sums in cents (no 0.1+0.2 drift)", () => expect(previewTotal([{ price: 0.1, qty: 1 }, { price: 0.2, qty: 1 }])).toBe(0.3));
  it("empty is 0", () => expect(previewTotal([])).toBe(0));
});

describe("what is sent to /quote (real posApi)", () => {
  it("uses variant_id + quantity from the replacement lines", async () => {
    const lines = addReplacement([], v()).lines;
    await posApi.quote("s1", { items: lines.map((l) => ({ variant_id: l.variantId, quantity: l.qty })) });
    const [path, opts] = api.mock.calls.at(-1);
    expect(path).toBe("/pos/sessions/s1/quote");
    expect(opts.body).toEqual({ items: [{ variant_id: "n1", quantity: 1 }] });
  });
});
