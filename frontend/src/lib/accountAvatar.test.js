import { describe, expect, it } from "vitest";
import { avatarColor, initialsOf } from "./accountAvatar";

describe("initialsOf", () => {
  it("takes the first two name parts", () => {
    expect(initialsOf({ full_name: "Hamed Adel", email: "h@example.com" })).toBe("HA");
  });

  it("falls back to the email local part when no name is stored", () => {
    expect(initialsOf({ full_name: "   ", email: "7amedadel7@gmail.com" })).toBe("7A");
    expect(initialsOf({ email: "sally.m@x.com" })).toBe("SM");
  });

  it("never returns an empty string — an avatar with nothing in it reads as broken", () => {
    expect(initialsOf({})).toBe("؟");
    expect(initialsOf(null)).toBe("؟");
  });

  it("takes the first two letters of a one-part name", () => {
    expect(initialsOf({ full_name: "مريم" })).toBe("مر");
    expect(initialsOf({ full_name: "Hamed" })).toBe("HA");
  });
});

describe("avatarColor", () => {
  it("is stable for the same seed", () => {
    expect(avatarColor("h@example.com")).toBe(avatarColor("h@example.com"));
  });

  it("stays inside the readable palette", () => {
    for (const seed of ["a@x.com", "b@x.com", "7amedadel7@gmail.com", "", "—"]) {
      expect(avatarColor(seed)).toMatch(/^#[0-9a-f]{6}$/);
    }
  });

  it("separates different accounts instead of painting everyone the same", () => {
    const colors = new Set(
      ["a@x.com", "b@x.com", "c@x.com", "d@x.com", "e@x.com", "f@x.com", "g@x.com", "h@x.com"].map(
        avatarColor,
      ),
    );
    expect(colors.size).toBeGreaterThan(1);
  });

  it("ignores case so the same address never gets two colors", () => {
    expect(avatarColor("H@Example.com")).toBe(avatarColor("h@example.com"));
  });
});
