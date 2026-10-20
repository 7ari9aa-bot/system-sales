import { describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { fetchReturnsLog } from "./usePosSale";

vi.mock("@/lib/api", () => ({
  api: vi.fn(async (path) => {
    if (path === "/pos/sessions") return [{ id: "A" }, { id: "B" }];
    if (path === "/pos/sessions/A/receipts")
      return [
        { id: "s1", kind: "sale", number: "POS-1", order_id: "o1", issued_at: "2026-10-20T09:00:00Z" },
        { id: "r1", kind: "return", number: "POS-RET-1", order_id: "o1", issued_at: "2026-10-20T10:00:00Z" },
      ];
    if (path === "/pos/sessions/B/receipts") return [];
    if (path === "/pos/receipts/r1") return { lines: [{ quantity: 1, total: "50.00" }] };
    throw new Error("unexpected path " + path);
  }),
}));

// Goes through the REAL posApi (no hand-made fake client), so a renamed client method fails here, not in the browser.
describe("fetchReturnsLog (real posApi)", () => {
  it("collects returns across shifts and links the sale receipt of the same order", async () => {
    const rows = await fetchReturnsLog();
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ number: "POS-RET-1", invoiceNumber: "POS-1", saleReceiptId: "s1", sessionId: "A", amount: 50, qty: 1 });
    expect(api).toHaveBeenCalledWith("/pos/sessions");
  });
});
