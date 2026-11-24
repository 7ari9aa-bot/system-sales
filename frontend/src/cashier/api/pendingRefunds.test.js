import { describe, expect, it } from "vitest";
import { mergePendingRefunds, withoutPendingRefund } from "./pendingRefunds";

describe("the pending-refund list", () => {
  it("keeps an older promise when a new operation returns its own", () => {
    // The report's blocker 4b: the list was replaced by the newest answer, so an older card
    // reversal disappeared from the screen while it was still pending in the database.
    const old = { refund_id: "r-old", method: "card", amount: "300.00", order_number: "INV-1" };
    const merged = mergePendingRefunds([old], []);
    expect(merged).toEqual([old]);
  });

  it("adds the new rows without dropping the previous ones", () => {
    const merged = mergePendingRefunds(
      [{ refund_id: "r-old", method: "card", amount: "300.00" }],
      [{ refund_id: "r-new", method: "card", amount: "50.00" }],
    );
    expect(merged.map((r) => r.refund_id)).toEqual(["r-old", "r-new"]);
  });

  it("does not duplicate the same refund", () => {
    const merged = mergePendingRefunds(
      [{ refund_id: "r1", amount: "10.00" }],
      [{ refund_id: "r1", amount: "10.00", order_number: "INV-9" }],
    );
    expect(merged).toHaveLength(1);
    expect(merged[0].order_number).toBe("INV-9");
  });

  it("drops a row once it is settled", () => {
    const rows = [{ refund_id: "r1" }, { refund_id: "r2" }];
    expect(withoutPendingRefund(rows, "r1").map((r) => r.refund_id)).toEqual(["r2"]);
  });
});
