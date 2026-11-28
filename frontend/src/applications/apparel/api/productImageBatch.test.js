import { beforeEach, describe, expect, it, vi } from "vitest";

const calls = [];
let failNames = new Set();
// عدّاد الصور المفتوحة في نفس اللحظة: بيثبت إن الرفع متوازي ومحدود في نفس الوقت.
const active = { now: 0, peak: 0 };
vi.mock("@/lib/api", () => ({
  api: vi.fn(async (path, opts = {}) => {
    calls.push({ path, method: opts.method ?? "GET", body: opts.body });
    active.now += 1;
    active.peak = Math.max(active.peak, active.now);
    try {
      await new Promise((resolve) => setTimeout(resolve, 1));
      if (opts.body instanceof File && failNames.has(opts.body.name)) throw new Error("تخزين الصور غير متاح الآن");
      return { id: `img-${calls.length}`, url: "s3://x" };
    } finally {
      active.now -= 1;
    }
  }),
}));

import { deleteProductImage, reorderProductImages, bindProductImage, retryFailedImages, uploadProductImages } from "./productImage";

const png = (name) => new File([new Uint8Array([137, 80, 78, 71])], name, { type: "image/png" });
const ten = () => Array.from({ length: 10 }, (_, i) => png(`p${i}.png`));

describe("uploading a set of photos", () => {
  beforeEach(() => {
    calls.length = 0;
    failNames = new Set();
  });

  it("uploads ten photos in parallel, not one after another", async () => {
    active.now = 0;
    active.peak = 0;
    const progress = [];
    const { uploaded } = await uploadProductImages("p1", ten(), {
      onProgress: (i, s) => progress.push(`${i}:${s.status}`),
    });
    expect(uploaded).toHaveLength(10);
    expect(active.peak).toBeGreaterThan(1);
    expect(active.peak).toBeLessThanOrEqual(3);
    expect(progress.filter((p) => p.endsWith(":done"))).toHaveLength(10);
  });

  it("reports the failed photo alone and retries only it", async () => {
    failNames = new Set(["p3.png"]);
    const { uploaded, failed } = await uploadProductImages("p1", ten());
    expect(uploaded).toHaveLength(9);
    expect(failed).toHaveLength(1);
    expect(failed[0].name).toBe("p3.png");

    failNames = new Set();
    calls.length = 0;
    const retry = await retryFailedImages("p1", failed);
    expect(retry.uploaded).toHaveLength(1);
    expect(calls).toHaveLength(1);
  });
});

describe("managing saved photos", () => {
  beforeEach(() => {
    calls.length = 0;
  });

  it("deletes a saved photo", async () => {
    await deleteProductImage("p1", "img-9");
    expect(calls[0]).toMatchObject({ path: "/products/p1/images/img-9", method: "DELETE" });
  });

  it("saves the gallery order", async () => {
    await reorderProductImages("p1", ["b", "a"]);
    expect(calls[0].body).toEqual({ image_ids: ["b", "a"] });
  });

  it("binds a photo to a colour and can unbind it", async () => {
    await bindProductImage("p1", "img-9", "v-red");
    expect(calls[0].body).toEqual({ variant_id: "v-red" });
    await bindProductImage("p1", "img-9", null);
    expect(calls[1].body).toEqual({ unbind_variant: true });
  });
});
