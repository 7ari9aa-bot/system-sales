import { describe, expect, it } from "vitest";
import {
  MAX_COLORS_PER_PRODUCT,
  MAX_SIZES_PER_PRODUCT,
  MAX_VARIANTS_PER_PRODUCT,
  variantCount,
  variantLimitProblem,
} from "./productLimits";

describe("variant limits", () => {
  it("uses the same ceiling the backend enforces", () => {
    expect(MAX_VARIANTS_PER_PRODUCT).toBe(500);
  });

  it("counts colour × size before anything is generated", () => {
    expect(variantCount(["أسود", "أبيض"], ["S", "M", "L"])).toBe(6);
  });

  it("refuses the 200 × 60 matrix the shop settings allow", () => {
    const colors = Array.from({ length: MAX_COLORS_PER_PRODUCT }, (_, i) => `لون${i}`);
    const sizes = Array.from({ length: MAX_SIZES_PER_PRODUCT }, (_, i) => `مقاس${i}`);
    const problem = variantLimitProblem(colors, sizes);
    expect(problem).toContain("12000");
    expect(problem).toContain("500");
  });

  it("lets a normal clothing matrix through", () => {
    expect(variantLimitProblem(["أسود", "كحلي"], ["S", "M", "L", "XL"])).toBe(null);
  });

  it("asks for at least one colour and one size", () => {
    expect(variantLimitProblem([], ["M"])).toBeTruthy();
  });
});
