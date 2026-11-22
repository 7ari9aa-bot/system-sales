import { describe, expect, it } from "vitest";
import { productEditQueryOptions } from "./useCatalogWrite";

describe("how the edit page reads a product", () => {
  const opts = productEditQueryOptions("p1");
  it("retries a 503 but not a 404", () => {
    expect(opts.retry(0, { status: 503 })).toBe(true);
    expect(opts.retry(0, { status: 404 })).toBe(false);
  });
  it("stops retrying after a few tries", () => {
    expect(opts.retry(3, { status: 503 })).toBe(false);
  });
  it("waits longer between tries, never more than 6 seconds", () => {
    expect(opts.retryDelay(0)).toBe(1000);
    expect(opts.retryDelay(1)).toBe(2000);
    expect(opts.retryDelay(10)).toBe(6000);
  });
  it("always reads fresh, never from a stale copy", () => {
    expect(opts.staleTime).toBe(0);
  });
});
