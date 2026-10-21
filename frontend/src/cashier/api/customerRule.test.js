import { describe, expect, it } from "vitest";
import { customerBlock, sellableCustomers } from "./customerRule";

describe("customerBlock: a till that requires a customer", () => {
  it("blocks the sale when no customer is picked", () => {
    expect(customerBlock({ requireCustomer: true, customerId: undefined })).toMatch(/عميل/);
  });
  it("lets it through once a real customer is picked", () => {
    expect(customerBlock({ requireCustomer: true, customerId: "c1" })).toBeNull();
  });
  it("never blocks a till that does not require one", () => {
    expect(customerBlock({ requireCustomer: false, customerId: undefined })).toBeNull();
  });
});

describe("sellableCustomers", () => {
  it("drops blocked customers and accepts both list shapes", () => {
    const rows = [{ id: "a", is_blocked: false }, { id: "b", is_blocked: true }];
    expect(sellableCustomers({ items: rows }).map((c) => c.id)).toEqual(["a"]);
    expect(sellableCustomers(rows).map((c) => c.id)).toEqual(["a"]);
    expect(sellableCustomers(null)).toEqual([]);
  });
});
