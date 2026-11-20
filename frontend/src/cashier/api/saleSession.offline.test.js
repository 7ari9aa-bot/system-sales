import { beforeEach, describe, expect, it, vi } from "vitest";

const { recordSale } = vi.hoisted(() => ({ recordSale: vi.fn() }));
vi.mock("./posApi", async () => {
  const actual = await vi.importActual("./posApi");
  return { ...actual, posApi: { recordSale, receipt: vi.fn(), quote: vi.fn() } };
});

import { createSaleSession } from "./saleSession";
import { enqueueOfflineSale } from "../lib/offlineQueue";
import { posApi } from "./posApi";

const cart = [
  { variantId: "v1", qty: 2, discountPct: 10 },
  { variantId: "v2", qty: 1, discountPct: 0 },
];
const sale = {
  cart,
  discountTotal: "5.00",
  customerId: "c1",
  customerPhone: "01012345678",
  customerName: "Ali",
  note: "gift",
};

beforeEach(() => recordSale.mockReset());

describe("an offline sale is the SAME sale the online path would have sent", () => {
  it("carries the customer, the invoice discount and the line discount", () => {
    const { payload } = createSaleSession("s1", "r1").offlineSnapshot(sale);
    expect(payload.customerId).toBe("c1");
    expect(payload.discountTotal).toBe("5.00");
    expect(payload.note).toBe("gift");
    expect(payload.items).toEqual([
      { variant_id: "v1", quantity: 2, discount_pct: "10.00" },
      { variant_id: "v2", quantity: 1 },
    ]);
  });

  it("a walk-in with a phone keeps name and phone (they are dropped only when a customer is picked)", () => {
    const { payload } = createSaleSession("s1", "r1").offlineSnapshot({ ...sale, customerId: undefined });
    expect(payload.customerPhone).toBe("01012345678");
    expect(payload.customerName).toBe("Ali");
    expect(payload.customerId).toBeUndefined();
  });

  it("replayed through recordSale it reaches the wire intact", async () => {
    const { payload, intentKey } = createSaleSession("s1", "r1").offlineSnapshot(sale);
    const rec = await enqueueOfflineSale({ registerId: "r1", payload, intentKey });
    await posApi.recordSale(rec.data.registerId, rec.data.payload, { key: rec.intent_key });
    const [, sent, intent] = recordSale.mock.calls[0];
    expect(sent.customerId).toBe("c1");
    expect(sent.discountTotal).toBe("5.00");
    expect(intent.key).toBe(intentKey);
  });
});

describe("the key of a sale that may already have reached the server is kept", () => {
  it("a tap that failed on the network and is then queued offline replays under the SAME key", async () => {
    recordSale.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const s = createSaleSession("s1", "r1");
    await expect(s.confirm(sale)).rejects.toThrow("Failed to fetch");
    const sentKey = recordSale.mock.calls[0][2].key;
    const { intentKey } = s.offlineSnapshot(sale);
    expect(intentKey).toBe(sentKey);
  });

  it("a different cart is a different sale and gets a different key", async () => {
    recordSale.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const s = createSaleSession("s1", "r1");
    await expect(s.confirm(sale)).rejects.toThrow();
    const sentKey = recordSale.mock.calls[0][2].key;
    const other = s.offlineSnapshot({ ...sale, cart: [{ variantId: "v9", qty: 1, discountPct: 0 }] });
    expect(other.intentKey).not.toBe(sentKey);
  });

  it("with nothing sent yet the snapshot mints a fresh key, and asking twice gives the same one", () => {
    const s = createSaleSession("s1", "r1");
    const a = s.offlineSnapshot(sale).intentKey;
    expect(a.length).toBeGreaterThanOrEqual(8);
    expect(s.offlineSnapshot(sale).intentKey).toBe(a);
  });
});
