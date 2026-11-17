import { describe, expect, it } from "vitest";
import { COMMANDS, buildReceiptEscPos } from "./escpos";

describe("ESC/POS binary builder", () => {
  it("includes initialization command and drawer kick byte sequence", () => {
    expect(COMMANDS.INIT[0]).toBe(0x1b);
    expect(COMMANDS.INIT[1]).toBe(0x40);
    expect(COMMANDS.DRAWER_KICK[0]).toBe(0x1b);
    expect(COMMANDS.DRAWER_KICK[1]).toBe(0x70);
  });

  it("builds a formatted receipt containing store name, items, totals, and cut command", () => {
    const bytes = buildReceiptEscPos({
      shopName: "My Test Store",
      receiptNumber: "REC-1001",
      items: [
        { name: "Coffee", quantity: 2, unit_price: "15.00", total: "30.00" },
        { name: "Croissant", quantity: 1, unit_price: "25.00", total: "25.00" },
      ],
      total: "55.00",
      discount: "5.00",
      tax: "7.00",
      cut: true,
    });

    expect(bytes).toBeInstanceOf(Uint8Array);
    expect(bytes.length).toBeGreaterThan(50);

    const decoded = new TextDecoder().decode(bytes);
    expect(decoded).toContain("My Test Store");
    expect(decoded).toContain("Receipt #: REC-1001");
    expect(decoded).toContain("Coffee");
    expect(decoded).toContain("Croissant");
    expect(decoded).toContain("TOTAL:");
    expect(decoded).toContain("55.00");
  });
});
