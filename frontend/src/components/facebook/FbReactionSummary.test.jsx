import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import FbReactionSummary from "@/components/facebook/FbReactionSummary";

const html = (props) => renderToStaticMarkup(<FbReactionSummary lang="en" total={12} {...props} />);

describe("a post's reactions summary", () => {
  it("shows nothing when there are no reactions", () => {
    expect(html({ total: 0 })).toBe("");
  });
  it("shows a Like badge and the total before any breakdown is known", () => {
    const out = html({});
    expect(out).toContain('data-kind="LIKE"');
    expect(out).toContain(">12<");
  });
  it("is a button that can be focused, so the breakdown is not hover-only", () => {
    const out = html({});
    expect(out).toMatch(/<button\b[^>]*type="button"/);
    expect(out).toContain("aria-haspopup");
  });
  it("shows the most used kinds as badges once the breakdown is loaded", () => {
    const out = html({ kinds: { LIKE: 7, LOVE: 4, HAHA: 1 } });
    expect(out.indexOf('data-kind="LIKE"')).toBeLessThan(out.indexOf('data-kind="LOVE"'));
    expect(out).toContain('data-kind="HAHA"');
  });
  it("lists every kind with its count in the open panel, named in the page language", () => {
    const out = html({ open: true, kinds: { LIKE: 7, LOVE: 4 } });
    expect(out).toContain('role="tooltip"');
    expect(out).toContain("Love");
    expect(out).toContain(">4<");
  });
  it("names the kinds in Arabic", () => {
    expect(html({ lang: "ar", open: true, kinds: { LOVE: 4 } })).toContain("أحببته");
  });
});
