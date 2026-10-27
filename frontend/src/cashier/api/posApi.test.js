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

describe("a recorded sale carries no payment and never a bad figure", () => {
  it("recordSale sends a typed phone and name trimmed, and omits them when blank", async () => {
    await posApi.recordSale("r1", { items: [{ variant_id: "v", quantity: 1 }], customerPhone: " 01012345678 ", customerName: " أحمد " }, newIntent());
    const withPhone = calls[0].body;
    expect(withPhone.customer_phone).toBe("01012345678");
    expect(withPhone.customer_name).toBe("أحمد");
    await posApi.recordSale("r1", { items: [{ variant_id: "v", quantity: 1 }], customerPhone: "  ", customerName: "" }, newIntent());
    const blank = calls[1].body;
    expect(blank).not.toHaveProperty("customer_phone");
    expect(blank).not.toHaveProperty("customer_name");
  });

  it("recordSale sends the items, the discount as a wire string, and no tender", async () => {
    await posApi.recordSale(
      "r1",
      { items: [{ variant_id: "v1", quantity: 2 }], discountTotal: 5.5, note: "  gift  " },
      newIntent(),
    );
    const body = calls[0].body;
    expect(calls[0].path).toBe("/pos/registers/r1/sales");
    expect(body.discount_total).toBe("5.50");
    expect(body.note).toBe("gift");
    expect(body.tenders).toBeUndefined();
    expect(body.tendered_cash).toBeUndefined();
  });

  it("refuses a negative discount before any request is made", async () => {
    await expect(
      posApi.recordSale("r1", { items: [{ variant_id: "v", quantity: 1 }], discountTotal: -5 }, newIntent()),
    ).rejects.toThrow(/negative/i);
    expect(calls).toHaveLength(0);
  });

  it("refuses an empty cart and a non-positive quantity", async () => {
    await expect(posApi.recordSale("r1", { items: [] }, newIntent())).rejects.toThrow(/item/i);
    await expect(
      posApi.recordSale("r1", { items: [{ variant_id: "v", quantity: 0 }] }, newIntent()),
    ).rejects.toThrow(/quantity/i);
    expect(calls).toHaveLength(0);
  });
});

describe("retry safety: one intent = one Idempotency-Key", () => {
  it("every money call carries the key of its intent", async () => {
    const intent = newIntent();
    await posApi.recordSale("r1", { items: [{ variant_id: "v", quantity: 1 }] }, intent);
    await posApi.returnSale("s1", { orderId: "o1", lines: [{ variant_id: "v", quantity: 1 }] }, newIntent());
    await posApi.exchange("s1", { orderId: "o1", returnLines: [{ variant_id: "v", quantity: 1 }], newLines: [{ variant_id: "w", quantity: 1 }] }, newIntent());
    for (const c of calls) expect(c.headers["Idempotency-Key"]).toMatch(/^[\w-]{16,}$/);
    expect(calls[0].headers["Idempotency-Key"]).toBe(intent.key);
  });

  it("re-sending the SAME intent re-sends the SAME key (a retry, not a second sale)", async () => {
    const intent = newIntent();
    const cart = { items: [{ variant_id: "v", quantity: 1 }] };
    await posApi.recordSale("r1", cart, intent);
    await posApi.recordSale("r1", cart, intent);
    expect(calls[0].headers["Idempotency-Key"]).toBe(calls[1].headers["Idempotency-Key"]);
  });

  it("a NEW intent gets a NEW key (a second, deliberate sale)", () => {
    expect(newIntent().key).not.toBe(newIntent().key);
  });

  it("calling a money endpoint without an intent is a programming error", async () => {
    await expect(posApi.recordSale("r1", { items: [{ variant_id: "v", quantity: 1 }] })).rejects.toThrow(/intent/i);
    expect(calls).toHaveLength(0);
  });
});

describe("routes", () => {
  it("hits the documented paths", async () => {
    await posApi.listRegisters();
    await posApi.listProfiles();
    await posApi.openDay("r1", "100.00");
    await posApi.closePreview("s1");
    await posApi.closeSession("s1");
    await posApi.scan("s1", { identifierType: "barcode", value: "123" });
    await posApi.heldCarts("s1");
    expect(calls.map((c) => `${c.method ?? "GET"} ${c.path}`)).toEqual([
      "GET /pos/registers",
      "GET /pos/profiles",
      "POST /pos/registers/r1/open-day",
      "GET /pos/sessions/s1/close-preview",
      "POST /pos/sessions/s1/close",
      "POST /pos/sessions/s1/scan",
      "GET /pos/sessions/s1/held-carts",
    ]);
    expect(calls[2].body).toEqual({ opening_float: "100.00" });
    expect(calls[4].body).toEqual({}); // nothing is counted at the close
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
