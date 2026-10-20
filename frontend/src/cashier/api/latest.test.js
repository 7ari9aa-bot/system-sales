import { describe, expect, it } from "vitest";
import { discountMinor, latestOnly } from "./latest";

describe("latestOnly: a slow old answer must never overwrite a newer one", () => {
  it("only the most recent call's result is delivered", async () => {
    const seen = [];
    const run = latestOnly((v) => seen.push(v));
    let slow;
    const a = run(() => new Promise((r) => (slow = r)));
    const b = run(() => Promise.resolve("new"));
    await b;
    slow("old");
    await a;
    expect(seen).toEqual(["new"]);
  });
  it("a failure of a superseded call is swallowed, the latest failure is reported", async () => {
    const errs = [];
    const run = latestOnly(() => {}, (e) => errs.push(e.message));
    const a = run(() => Promise.reject(new Error("stale")));
    const b = run(() => Promise.reject(new Error("fresh")));
    await Promise.all([a, b]);
    expect(errs).toEqual(["fresh"]);
  });
  it("cancel() drops a pending result (cart emptied while a quote was in flight)", async () => {
    const seen = [];
    const run = latestOnly((v) => seen.push(v));
    let done;
    const p = run(() => new Promise((r) => (done = r)));
    await Promise.resolve(); // let the work start before cancelling
    run.cancel();
    done("late");
    await p;
    expect(seen).toEqual([]);
  });
});

describe("discountMinor", () => {
  const lines = [{ price: 25, qty: 2, discountPct: 10 }, { price: 10, qty: 1, discountPct: 0 }];
  it("sums line percentages plus the invoice amount, in cents", () => {
    expect(discountMinor(lines, "2.50")).toBe(500 + 250); // 10% of 50.00 = 5.00, plus 2.50
  });
  it("no discounts is zero", () => expect(discountMinor([{ price: 10, qty: 1, discountPct: 0 }], "")).toBe(0));
  it("0.1+0.2 style amounts do not drift", () => {
    expect(discountMinor([{ price: 0.1, qty: 3, discountPct: 100 }], "")).toBe(30);
  });
  it("a blank or junk invoice discount counts as zero", () => {
    expect(discountMinor([], "abc")).toBe(0);
    expect(discountMinor([], undefined)).toBe(0);
  });
});
