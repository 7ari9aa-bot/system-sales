import { describe, expect, it } from "vitest";
import { createIntentStore, fingerprint } from "./intentStore";

const counter = () => {
  let n = 0;
  return () => ({ key: `pos-${String(++n).padStart(8, "0")}` });
};

describe("fingerprint", () => {
  it("ignores key order but sees every value", () => {
    expect(fingerprint({ a: 1, b: [1, 2] })).toBe(fingerprint({ b: [1, 2], a: 1 }));
    expect(fingerprint({ a: 1 })).not.toBe(fingerprint({ a: 2 }));
    expect(fingerprint({ a: [1, 2] })).not.toBe(fingerprint({ a: [2, 1] })); // line order matters
    expect(fingerprint({ a: "1" })).not.toBe(fingerprint({ a: 1 }));
  });
  it("handles null, undefined and nesting", () => {
    expect(fingerprint(null)).toBe("null");
    expect(fingerprint(undefined)).toBe("undefined");
    expect(fingerprint({ a: { b: { c: [{ d: 1 }] } } })).toBe(fingerprint({ a: { b: { c: [{ d: 1 }] } } }));
  });
});

describe("intent store", () => {
  it("the same content again reuses the key (a retry after a lost response must replay)", () => {
    const s = createIntentStore(counter());
    const a = s.take("create", { amount: "5.00" });
    expect(s.take("create", { amount: "5.00" })).toBe(a);
    expect(s.take("create", { amount: "5.00" })).toBe(a);
  });
  it("changed content gets a NEW key (the user fixed something: a new intention)", () => {
    const s = createIntentStore(counter());
    const a = s.take("create", { amount: "5.00" });
    const b = s.take("create", { amount: "6.00" });
    expect(b.key).not.toBe(a.key);
  });
  it("after fixing and failing again with the ORIGINAL content, it is a new intent too (no stale replay)", () => {
    const s = createIntentStore(counter());
    const a = s.take("create", { n: 1 });
    s.take("create", { n: 2 });
    expect(s.take("create", { n: 1 }).key).not.toBe(a.key);
  });
  it("a success forgets the key, so the next deliberate action starts fresh", () => {
    const s = createIntentStore(counter());
    const a = s.take("create", { n: 1 });
    s.done("create");
    expect(s.take("create", { n: 1 }).key).not.toBe(a.key);
    expect(s.size()).toBe(1);
  });
  it("slots are independent", () => {
    const s = createIntentStore(counter());
    const a = s.take("pay:1", { x: 1 });
    const b = s.take("pay:2", { x: 1 });
    expect(a.key).not.toBe(b.key);
    s.done("pay:1");
    expect(s.take("pay:2", { x: 1 })).toBe(b);
  });
  it("a call with no body (receive / cancel) still keeps one key per slot", () => {
    const s = createIntentStore(counter());
    const a = s.take("receive:1", undefined);
    expect(s.take("receive:1", undefined)).toBe(a);
  });
});
