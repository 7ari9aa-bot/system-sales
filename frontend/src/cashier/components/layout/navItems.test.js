import { describe, expect, it } from "vitest";
import { cashierNavItems, navGroups, pageTitle } from "./navItems";

/** كل مسار في السايدبار، الأب والأبناء، مرة واحدة. */
function allItems() {
  return navGroups.flatMap((group) =>
    group.items.flatMap((item) => [item, ...(item.children ?? [])]),
  );
}

describe("the cashier sidebar", () => {
  it("never points two entries at the same page", () => {
    const paths = allItems().map((item) => item.to);
    expect(new Set(paths).size).toBe(paths.length);
  });

  it("gives every entry a label and an icon", () => {
    for (const item of allItems()) {
      expect(item.label?.trim().length ?? 0).toBeGreaterThan(0);
      expect(item.icon).toBeTruthy();
    }
  });

  it("keeps every child under its parent's path", () => {
    for (const item of navGroups.flatMap((group) => group.items)) {
      for (const child of item.children ?? []) {
        expect(child.to.startsWith(`${item.to}/`)).toBe(true);
      }
    }
  });

  it("has one entry per page, not one page holding several", () => {
    // سلاسل الإمداد كانت صفحة واحدة بـ7 تبويبات: دلوقتي كل وحدة بندها.
    const supplyChain = navGroups.flatMap((g) => g.items).find((i) => i.to === "/supply-chain");
    expect(supplyChain?.children).toHaveLength(7);
    expect(new Set(supplyChain.children.map((c) => c.to)).size).toBe(7);
  });

  it("names the page you are on, including the supply-chain modules", () => {
    expect(pageTitle("/cashier/supply-chain/receipts")).toBe("أذونات الاستلام والجودة");
    expect(pageTitle("/cashier/supply-chain/traceability")).toBe("التتبع والدفعات والسيريال");
    expect(pageTitle("/inventory/stocktake")).toBe("الجرد الفعلي");
    expect(pageTitle("/pos")).toBe("الكاشير");
  });

  it("keeps the flat list in step with the groups", () => {
    expect(cashierNavItems).toHaveLength(navGroups.reduce((n, g) => n + g.items.length, 0));
  });
});
