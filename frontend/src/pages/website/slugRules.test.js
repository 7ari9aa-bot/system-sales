import { describe, expect, it } from "vitest";

import { RESERVED_SLUGS, SLUG_MAX_LENGTH, slugError, slugify } from "./slugRules";

describe("slugRules — mirrors the server's website/slugs.py", () => {
  it("accepts a normal slug", () => {
    expect(slugError("my-shop-1")).toBeNull();
    expect(slugError("abc")).toBeNull();
  });

  it("rejects the same shapes the server rejects", () => {
    expect(slugError("ab")).toBe("format"); // too short for the regex
    expect(slugError("-leading")).toBe("format");
    expect(slugError("trailing-")).toBe("format");
    expect(slugError("Has-Caps")).toBe("format");
    expect(slugError("under_score")).toBe("format");
    expect(slugError("a".repeat(SLUG_MAX_LENGTH + 1))).toBe("format");
  });

  it("rejects reserved names with the dedicated code", () => {
    for (const reserved of ["api", "www", "admin"]) {
      expect(RESERVED_SLUGS.has(reserved)).toBe(true);
      expect(slugError(reserved)).toBe("reserved");
    }
  });

  it("slugifies latin names and yields nothing for arabic-only ones", () => {
    expect(slugify("Ahmed Store")).toBe("ahmed-store");
    expect(slugify("متجري")).toBe("");
  });
});
