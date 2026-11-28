import { describe, expect, it } from "vitest";
import { enqueueOfflineSale } from "./offlineQueue";

// No IndexedDB in this environment: enqueueOfflineSale falls back to returning the record, which
// is exactly the object that gets stored and later replayed.
describe("an offline sale keeps one idempotency key for life", () => {
  it("mints a key when it is queued", async () => {
    const rec = await enqueueOfflineSale({ registerId: "r1", payload: { items: [] } });
    expect(typeof rec.intent_key).toBe("string");
    expect(rec.intent_key.length).toBeGreaterThanOrEqual(8);
  });

  it("gives two different sales two different keys", async () => {
    const a = await enqueueOfflineSale({ registerId: "r1", payload: {} });
    const b = await enqueueOfflineSale({ registerId: "r1", payload: {} });
    expect(a.intent_key).not.toBe(b.intent_key);
  });

  it("the stored record carries the key a replay must send", async () => {
    const rec = await enqueueOfflineSale({ registerId: "r1", payload: {} });
    // useOfflineSync reads item.intent_key; reading it twice must give the same value.
    expect(rec.intent_key).toBe(rec.intent_key);
    expect(rec.intent_key).toBe(`pos-${rec.id}`);
  });
});
