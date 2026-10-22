import { beforeEach, describe, expect, it, vi } from "vitest";

const calls = [];
vi.mock("@/lib/api", () => ({
  api: vi.fn(async (path, opts = {}) => {
    calls.push({ path, ...opts });
    return { ok: true };
  }),
}));

import { newIntent, posApi } from "./posApi";

beforeEach(() => {
  calls.length = 0;
});

describe("money never leaves as a float or a negative", () => {
  it("sell sends wire strings, tenders summed from cents", async () => {
    const intent = newIntent();
    await posApi.sell("s1", {
      items: [{ variant_id: "v1", quantity: 2 }],
      tenders: [
        { method: "cash", amount: 10.1 },
        { method: "card", amount: "20.20" },
      ],
      tenderedCash: 20,
    }, intent);
    const body = calls[0].body;
    expect(body.tenders).toEqual([
      { method: "cash", amount: "10.10" },
      { method: "card", amount: "20.20" },
    ]);
    expect(body.tendered_cash).toBe("20.00");
  });

  it("refuses a negative amount before any request is made", async () => {
    await expect(
      posApi.cashMovement("s1", { direction: "out", reason: "pay_out", amount: -5 }, newIntent()),
    ).rejects.toThrow(/negative/i);
    expect(calls).toHaveLength(0);
  });

  it("refuses a malformed method/direction before any request is made", async () => {
    await expect(
      posApi.sell("s1", { items: [{ variant_id: "v", quantity: 1 }], tenders: [{ method: "bitcoin", amount: 1 }] }, newIntent()),
    ).rejects.toThrow(/method/i);
    await expect(
      posApi.cashMovement("s1", { direction: "sideways", reason: "pay_out", amount: 1 }, newIntent()),
    ).rejects.toThrow(/direction/i);
    expect(calls).toHaveLength(0);
  });

  it("refuses an empty cart and a non-positive quantity", async () => {
    await expect(posApi.sell("s1", { items: [], tenders: [{ method: "cash", amount: 1 }] }, newIntent())).rejects.toThrow(/item/i);
    await expect(
      posApi.sell("s1", { items: [{ variant_id: "v", quantity: 0 }], tenders: [{ method: "cash", amount: 1 }] }, newIntent()),
    ).rejects.toThrow(/quantity/i);
    expect(calls).toHaveLength(0);
  });
});

describe("retry safety: one intent = one Idempotency-Key", () => {
  it("every money call carries the key of its intent", async () => {
    const intent = newIntent();
    await posApi.sell("s1", { items: [{ variant_id: "v", quantity: 1 }], tenders: [{ method: "cash", amount: 5 }] }, intent);
    await posApi.refund("s1", { orderId: "o1", amount: 5, method: "cash" }, newIntent());
    await posApi.returnSale("s1", { orderId: "o1", lines: [{ variant_id: "v", quantity: 1 }] }, newIntent());
    await posApi.exchange("s1", { orderId: "o1", returnLines: [{ variant_id: "v", quantity: 1 }], newLines: [{ variant_id: "w", quantity: 1 }] }, newIntent());
    await posApi.cashMovement("s1", { direction: "in", reason: "pay_in", amount: 1 }, newIntent());
    for (const c of calls) expect(c.headers["Idempotency-Key"]).toMatch(/^[\w-]{16,}$/);
    expect(calls[0].headers["Idempotency-Key"]).toBe(intent.key);
  });

  it("re-sending the SAME intent re-sends the SAME key (a retry, not a second sale)", async () => {
    const intent = newIntent();
    const cart = { items: [{ variant_id: "v", quantity: 1 }], tenders: [{ method: "cash", amount: 5 }] };
    await posApi.sell("s1", cart, intent);
    await posApi.sell("s1", cart, intent);
    expect(calls[0].headers["Idempotency-Key"]).toBe(calls[1].headers["Idempotency-Key"]);
  });

  it("a NEW intent gets a NEW key (a second, deliberate sale)", () => {
    expect(newIntent().key).not.toBe(newIntent().key);
  });

  it("calling a money endpoint without an intent is a programming error", async () => {
    await expect(posApi.sell("s1", { items: [{ variant_id: "v", quantity: 1 }], tenders: [{ method: "cash", amount: 1 }] })).rejects.toThrow(/intent/i);
    expect(calls).toHaveLength(0);
  });
});

describe("routes", () => {
  it("hits the documented paths", async () => {
    await posApi.listRegisters();
    await posApi.listProfiles();
    await posApi.openSession("r1", { openingFloat: 100, floatsByMethod: { cash: 100 } });
    await posApi.closePreview("s1");
    await posApi.closeSession("s1", { countedCash: 95 });
    await posApi.scan("s1", { identifierType: "barcode", value: "123" });
    await posApi.heldCarts("s1");
    expect(calls.map((c) => `${c.method ?? "GET"} ${c.path}`)).toEqual([
      "GET /pos/registers",
      "GET /pos/profiles",
      "POST /pos/registers/r1/sessions",
      "GET /pos/sessions/s1/close-preview",
      "POST /pos/sessions/s1/close",
      "POST /pos/sessions/s1/scan",
      "GET /pos/sessions/s1/held-carts",
    ]);
    expect(calls[2].body).toEqual({ opening_float: "100.00", floats_by_method: { cash: "100.00" } });
    expect(calls[4].body).toEqual({ counted_cash: "95.00" });
  });

  it("encodes path segments", async () => {
    await posApi.closePreview("a/b?c");
    expect(calls[0].path).toBe("/pos/sessions/a%2Fb%3Fc/close-preview");
  });
});

describe("posApi stock", () => {
  it("setReorderLevel refuses a level the server would reject, before any request", () => {
    for (const bad of [-1, 2.5, "3", null, NaN, 1_000_001]) {
      expect(() => posApi.setReorderLevel("v1", bad)).toThrow(RangeError);
    }
  });
});

describe("receipt search", () => {
  it("asks the cross-shift endpoint and escapes what the cashier typed", async () => {
    await posApi.searchReceipts("POS 1&limit=500%");
    expect(calls[0].path).toBe("/pos/receipts/search?q=POS%201%26limit%3D500%25&limit=20");
  });

  it("never lets the typed text add or override a query parameter", async () => {
    await posApi.searchReceipts("x&limit=500", 5);
    const url = new URL(calls[0].path, "http://x");
    expect(url.searchParams.getAll("limit")).toEqual(["5"]);
    expect(url.searchParams.get("q")).toBe("x&limit=500");
  });
});

describe("recordSale note", () => {
  const items = [{ variant_id: "v1", quantity: 1 }];

  it("sends the trimmed note as `note`", async () => {
    await posApi.recordSale("r1", { items, note: "  هدية  " }, newIntent());
    expect(calls[0].body.note).toBe("هدية");
  });

  it("leaves `note` out when it is missing or only spaces", async () => {
    await posApi.recordSale("r1", { items }, newIntent());
    await posApi.recordSale("r1", { items, note: "   " }, newIntent());
    expect(calls[0].body).not.toHaveProperty("note");
    expect(calls[1].body).not.toHaveProperty("note");
  });
});
