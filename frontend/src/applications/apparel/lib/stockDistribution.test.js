import { describe, expect, it } from "vitest";
import {
  allocationLabel,
  allocationProblem,
  planOpeningDistribution,
  secondaryWarehouses,
  withPrimaryWarehouse,
} from "./stockDistribution";

const shops = [
  { id: "w-shop", name: "المحل", is_active: true },
  { id: "w-store", name: "المخزن", is_active: true },
  { id: "w-old", name: "مخزن مقفول", is_active: false },
];

const row = (over) => ({ id: "r1", sku: "SKU-1", color: "أسود", size: "M", stock: 40, alloc: {}, ...over });

describe("splitting the opening balance over warehouses", () => {
  it("sends the rest to the chosen warehouse and one movement per other warehouse", () => {
    const rows = [row({ alloc: { "w-store": 30 } })];
    const plan = planOpeningDistribution(rows, shops, "w-shop");
    expect(plan.primaryStock.r1).toBe(10);
    expect(plan.movements).toEqual([
      { rowId: "r1", sku: "SKU-1", warehouseId: "w-store", warehouseName: "المخزن", quantity: 30 },
    ]);
  });

  it("keeps everything in one warehouse when nothing was distributed", () => {
    const plan = planOpeningDistribution([row()], shops, "w-shop");
    expect(plan.primaryStock.r1).toBe(40);
    expect(plan.movements).toEqual([]);
  });

  it("never asks the primary warehouse for a negative balance", () => {
    const plan = planOpeningDistribution([row({ alloc: { "w-store": 60 } })], shops, "w-shop");
    expect(plan.primaryStock.r1).toBe(0);
    expect(plan.movements).toHaveLength(1);
  });

  it("ignores inactive warehouses", () => {
    expect(secondaryWarehouses(shops, "w-shop").map((w) => w.id)).toEqual(["w-store"]);
    const plan = planOpeningDistribution([row({ alloc: { "w-old": 5 } })], shops, "w-shop");
    expect(plan.movements).toEqual([]);
    expect(plan.primaryStock.r1).toBe(40);
  });
});

describe("refusing a distribution that does not add up", () => {
  it("names the variant when the split is bigger than its balance", () => {
    const problem = allocationProblem([row({ alloc: { "w-store": 55 } })], shops, "w-shop");
    expect(problem).toContain("أسود / M");
    expect(problem).toContain("55 من 40");
  });

  it("accepts a split that leaves zero in the primary warehouse", () => {
    expect(allocationProblem([row({ alloc: { "w-store": 40 } })], shops, "w-shop")).toBe("");
  });

  it("asks for a warehouse before talking about distribution", () => {
    expect(allocationProblem([row()], shops, "")).toContain("اختر المخزن");
  });
});

describe("changing the receiving warehouse", () => {
  it("drops a split aimed at the warehouse that just became the primary one", () => {
    const rows = [row({ alloc: { "w-store": 30, "w-other": 5 } })];
    const next = withPrimaryWarehouse(rows, "w-store");
    expect(next[0].alloc).toEqual({ "w-other": 5 });
    expect(next[0].stock).toBe(40);
  });

  it("describes the split in the shop's own words", () => {
    const rows = [row({ alloc: { "w-store": 30 } })];
    expect(allocationLabel(rows[0], shops, "w-shop")).toBe("المحل 10 · المخزن 30");
  });
});
