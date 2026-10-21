/**
 * Contract test: every (method, path) the cashier client actually sends must exist in the
 * committed OpenAPI lock (desktop/openapi.lock.json). Catches the wrong-path class of bug
 * (e.g. /catalog/warehouses vs /warehouses) in CI, not in front of a customer.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";

const { sent } = vi.hoisted(() => ({ sent: [] }));
vi.mock("@/lib/api", () => ({
  api: vi.fn(async (p, o = {}) => {
    sent.push({ method: (o.method ?? "GET").toUpperCase(), path: p.split("?")[0] });
    // enough shape for shiftState to walk its whole path
    if (p.startsWith("/warehouses")) return { id: "w1", is_active: true };
    if (p === "/pos/profiles" && !o.method) return [];
    if (p === "/pos/profiles") return { id: "p1" };
    if (p === "/pos/registers" && !o.method) return [];
    if (p === "/pos/registers") return { id: "r1", is_active: true };
    return {};
  }),
}));

import { bootstrapPos } from "./shiftState";
import { newIntent, posApi } from "./posApi";

const here = path.dirname(fileURLToPath(import.meta.url));
const lock = JSON.parse(fs.readFileSync(path.resolve(here, "../../../../desktop/openapi.lock.json"), "utf8"));
const norm = (p) => p.replace(/\{[^}]+\}/g, "{}");
const live = new Set(
  Object.entries(lock.spec?.paths ?? {}).flatMap(([p, ops]) =>
    Object.keys(ops).map((m) => `${m.toUpperCase()} ${norm(p.replace(/^\/api\/v1/, ""))}`),
  ),
);
const asKey = (c) => `${c.method} ${norm(c.path.replace(/\/[0-9a-f-]{8,}|\/(s1|r1|o1|h1|u1)(?=\/|$)/g, "/{}"))}`;

const I = () => newIntent();
const L = [{ variant_id: "v1", quantity: 1 }];
const T = [{ method: "cash", amount: 1 }];

describe("cashier client <-> committed OpenAPI lock", () => {
  it("the lock is loaded and has POS routes (guards against a vacuous pass)", () => {
    expect(live.size).toBeGreaterThan(100);
    expect(live.has("POST /pos/sessions/{}/sell")).toBe(true);
  });

  it("every call posApi can make exists in the backend contract", async () => {
    sent.length = 0;
    await posApi.listProfiles();
    await posApi.listRegisters();
    await posApi.listSessions("status=OPEN");
    await posApi.getSession("s1");
    await posApi.closePreview("s1");
    await posApi.reconciliation("s1");
    await posApi.report("s1");
    await posApi.receipts("s1");
    await posApi.receipt("s1");
    await posApi.searchReceipts("POS-001");
    await posApi.sessionItems("s1");
    await posApi.heldCarts("s1");
    await posApi.dailyReport();
    await posApi.openSession("r1", { openingFloat: 1 });
    await posApi.closeSession("s1", { countedCash: 1 });
    await posApi.scan("s1", { identifierType: "barcode", value: "1" });
    await posApi.quote("s1", { items: L });
    await posApi.holdCart("s1", { items: L });
    await posApi.releaseHeldCart("h1");
    await posApi.sell("s1", { items: L, tenders: T }, I());
    await posApi.refund("s1", { orderId: "o1", amount: 1 }, I());
    await posApi.returnSale("s1", { orderId: "o1", lines: L }, I());
    await posApi.exchange("s1", { orderId: "o1", returnLines: L, newLines: L }, I());
    await posApi.cashMovement("s1", { direction: "in", reason: "pay_in", amount: 1 }, I());
    await posApi.handover("s1", { toUserId: "u1", countedCash: 1 }, I());
    await posApi.stocktakes();
    await posApi.stocktake("h1");
    await posApi.openStocktake("note", I());
    await posApi.saveStocktakeCounts("h1", [{ variant_id: "v1", counted_qty: 1 }]);
    await posApi.approveStocktake("h1", I());
    await posApi.cancelStocktake("h1", I());
    const missing = sent.map(asKey).filter((k) => !live.has(k));
    expect(sent.length).toBeGreaterThanOrEqual(29);
    expect(missing).toEqual([]);
  });

  it("every call bootstrapPos makes exists in the backend contract", async () => {
    sent.length = 0;
    await bootstrapPos();
    const missing = sent.map(asKey).filter((k) => !live.has(k));
    expect(sent.some((c) => c.path === "/warehouses/ensure-default")).toBe(true);
    expect(missing).toEqual([]);
  });
});
