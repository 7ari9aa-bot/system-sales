import { describe, expect, it } from "vitest";
import { committedQty, shownQty, typedQty } from "./qtyDraft";

describe("typedQty", () => {
  it("keeps digits only", () => {
    expect(typedQty("12")).toBe("12");
    expect(typedQty("1.5")).toBe("15");
    expect(typedQty("-3")).toBe("3");
    expect(typedQty("1e2")).toBe("12");
    expect(typedQty("")).toBe("");
    expect(typedQty(null)).toBe("");
  });
  it("is at most 4 digits so a stuck key cannot build a huge number", () => {
    expect(typedQty("123456")).toBe("1234");
  });
});

describe("committedQty", () => {
  it("the cashier clears 1 and types 5: it is 5, not 15", () => {
    expect(committedQty("5", 1, 50)).toBe(5);
  });
  it("12 with 50 in stock is 12, not 50", () => {
    expect(committedQty("12", 1, 50)).toBe(12);
  });
  it("never more than is on the shelf", () => {
    expect(committedQty("99", 1, 8)).toBe(8);
  });
  it("0 is not a quantity: it becomes 1", () => {
    expect(committedQty("0", 3, 50)).toBe(1);
  });
  it("an empty box keeps the line's quantity instead of silently becoming 1", () => {
    expect(committedQty("", 7, 50)).toBe(7);
  });
  it("no stock: keeps the current quantity", () => {
    expect(committedQty("4", 2, 0)).toBe(2);
  });
});

describe("shownQty", () => {
  it("shows the draft while typing, the real quantity otherwise", () => {
    expect(shownQty("", 5)).toBe("");
    expect(shownQty("12", 5)).toBe("12");
    expect(shownQty(null, 5)).toBe("5");
  });
});
