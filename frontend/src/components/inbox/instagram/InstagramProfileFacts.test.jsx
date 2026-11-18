import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { InstagramProfileFacts, VerifiedBadge, compactCount } from "./InstagramProfileFacts";

const facts = (c, lang = "en") => renderToStaticMarkup(<InstagramProfileFacts conversation={c} lang={lang} />);

describe("compactCount", () => {
  test.each([[0, "0"], [950, "950"], [1000, "1K"], [12500, "12.5K"], [999999, "1000K"], [1200000, "1.2M"], [-3, ""], [NaN, ""]])("%s -> %j", (n, out) => expect(compactCount(n)).toBe(out));
});

describe("InstagramProfileFacts", () => {
  test("shows the follower count and who follows whom", () => {
    const h = facts({ followerCount: 12500, followsYou: true, youFollow: false });
    expect(h).toContain("12.5K");
    expect(h).toContain("followers");
    expect(h).toContain("Follows you");
    expect(h).not.toContain("You follow them");
  });
  test("both ways", () => expect(facts({ followsYou: true, youFollow: true })).toContain("Follows you · You follow them"));
  test("neither way is said out loud", () => expect(facts({ followsYou: false, youFollow: false })).toContain("Not following each other"));
  test("draws nothing when Instagram told us nothing", () => {
    expect(facts({ followerCount: null, followsYou: null, youFollow: null })).toBe("");
    expect(facts(undefined)).toBe("");
  });
  test("a zero count is still a fact", () => expect(facts({ followerCount: 0 })).toContain(">0<"));
  test("Arabic wording", () => {
    const h = facts({ followerCount: 1200, followsYou: true, youFollow: false }, "ar");
    expect(h).toContain("متابع");
    expect(h).toContain("يتابعك");
  });
});

describe("VerifiedBadge", () => {
  test("is named for screen readers in both languages", () => {
    expect(renderToStaticMarkup(<VerifiedBadge lang="en" />)).toContain('aria-label="Verified"');
    expect(renderToStaticMarkup(<VerifiedBadge lang="ar" />)).toContain('aria-label="حساب موثّق"');
  });
});
