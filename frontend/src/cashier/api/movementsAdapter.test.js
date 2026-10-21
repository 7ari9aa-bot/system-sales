import { describe, expect, it } from "vitest";
import { movementsFromApi, movementsQuery, reasonLabel } from "./movementsAdapter";

const row = (over = {}) => ({
  id: "m", variant_id: "v1", warehouse_id: "w1", direction: "in", quantity: 5, reason: "purchase",
  reference_type: null, reference_id: null, balance_after: 5, created_at: "2026-10-21T02:00:00+00:00", ...over,
});

describe("movementsFromApi", () => {
  it("signs in and out", () => {
    const [out, inn] = movementsFromApi([row({ id: "2", direction: "out", quantity: 2, reason: "sale", balance_after: 3 }), row({ id: "1" })]);
    expect(out).toMatchObject({ delta: -2, qtyIn: 0, qtyOut: 2, balance: 3 });
    expect(inn).toMatchObject({ delta: 5, qtyIn: 5, qtyOut: 0 });
  });

  it("a reservation row is availability only: no stock moved and no balance shown", () => {
    const [h] = movementsFromApi([row({ direction: "hold", reason: "reservation", quantity: 3, balance_after: 9 })]);
    expect(h).toMatchObject({ availabilityOnly: true, delta: 0, qtyIn: 0, qtyOut: 0, balance: null });
  });

  it("a stocktake adjust is the NEW COUNT; its effect is the change from the previous balance", () => {
    const rows = [
      row({ id: "3", direction: "adjust", quantity: 7, reason: "adjustment", balance_after: 7 }),
      row({ id: "2", direction: "out", quantity: 2, reason: "sale", balance_after: 10 }),
      row({ id: "1", direction: "in", quantity: 12, balance_after: 12 }),
    ];
    const adj = movementsFromApi(rows)[0];
    expect(adj).toMatchObject({ isCount: true, counted: 7, delta: -3, qtyOut: 3, balance: 7 });
  });

  it("an adjust that raises the stock shows as incoming", () => {
    const rows = [row({ id: "2", direction: "adjust", quantity: 20, reason: "adjustment", balance_after: 20 }), row({ id: "1", balance_after: 5 })];
    expect(movementsFromApi(rows)[0]).toMatchObject({ delta: 15, qtyIn: 15 });
  });

  it("an adjust whose previous row is outside the loaded window is unknown, never guessed", () => {
    const [a] = movementsFromApi([row({ direction: "adjust", quantity: 7, reason: "adjustment", balance_after: 7 })]);
    expect(a.delta).toBeNull();
    expect(a.qtyIn).toBe(0);
    expect(a.qtyOut).toBe(0);
  });

  it("reservation rows in between do not become the 'previous balance' of an adjust", () => {
    const rows = [
      row({ id: "3", direction: "adjust", quantity: 4, reason: "adjustment", balance_after: 4 }),
      row({ id: "2", direction: "hold", reason: "reservation", quantity: 1, balance_after: 99 }),
      row({ id: "1", balance_after: 10 }),
    ];
    expect(movementsFromApi(rows)[0].delta).toBe(-6);
  });

  it("keeps different stock positions apart", () => {
    const rows = [
      row({ id: "3", direction: "adjust", quantity: 4, reason: "adjustment", balance_after: 4, warehouse_id: "w1" }),
      row({ id: "2", balance_after: 100, warehouse_id: "w2" }),
      row({ id: "1", balance_after: 10, warehouse_id: "w1" }),
    ];
    expect(movementsFromApi(rows)[0].delta).toBe(-6);
  });

  it("is empty for nothing", () => {
    expect(movementsFromApi(undefined)).toEqual([]);
  });
});

describe("labels and query", () => {
  it("labels known reasons and passes an unknown one through", () => {
    expect(reasonLabel("sale")).toBe("بيع");
    expect(reasonLabel("weird")).toBe("weird");
  });
  it("sends only a known reason and a bounded limit", () => {
    const q = new URLSearchParams(movementsQuery({ variantId: "v1", reason: "nope", limit: 99999 }));
    expect(q.get("variant_id")).toBe("v1");
    expect(q.has("reason")).toBe(false);
    expect(q.get("limit")).toBe("500");
  });
});
