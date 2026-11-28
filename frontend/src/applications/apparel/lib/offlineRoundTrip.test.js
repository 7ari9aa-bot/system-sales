import { describe, expect, it, vi } from "vitest";

const { recordSale } = vi.hoisted(() => ({ recordSale: vi.fn(async () => ({ number: "POS-1" })) }));
vi.mock("../api/posApi", async () => {
  const actual = await vi.importActual("../api/posApi");
  return { ...actual, posApi: { recordSale } };
});

import { createSaleSession } from "../api/saleSession";
import { enqueueOfflineSale } from "./offlineQueue";

// What useOfflineSync does for each queued record, without React or IndexedDB.
async function replay(rec) {
  const { posApi } = await import("../api/posApi");
  const { registerId, payload } = rec.data;
  return posApi.recordSale(registerId, payload, { key: rec.intent_key });
}

describe("a sale queued offline reaches the server as the sale the cashier rang up", () => {
  it("customer, invoice discount, line discount and the original key all survive the queue", async () => {
    const s = createSaleSession("s1", "r1");
    const snap = s.offlineSnapshot({
      cart: [{ variantId: "v1", qty: 3, discountPct: 20 }],
      discountTotal: "7.50",
      customerId: "c9",
      note: "آجل",
    });
    const rec = await enqueueOfflineSale({ registerId: "r1", ...snap });
    await replay(rec);
    const [reg, body, intent] = recordSale.mock.calls[0];
    expect(reg).toBe("r1");
    expect(body).toMatchObject({ customerId: "c9", discountTotal: "7.50", note: "آجل" });
    expect(body.items).toEqual([{ variant_id: "v1", quantity: 3, discount_pct: "20.00" }]);
    expect(intent.key).toBe(snap.intentKey);
  });
});
