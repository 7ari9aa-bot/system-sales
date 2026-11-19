import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import FacebookRelinkNotice, { facebookNeedsRelink } from "@/pages/settings/FacebookRelinkNotice";

const fb = (over = {}) => ({ id: "facebook", connected: true, missingScopes: ["pages_manage_posts", "read_insights"], ...over });
const html = (channel, isAr = false) => renderToStaticMarkup(<FacebookRelinkNotice channel={channel} isAr={isAr} />);

describe("the Facebook re-link notice", () => {
  it("names the missing permissions and says what to press", () => {
    const out = html(fb());
    expect(out).toContain("pages_manage_posts, read_insights");
    expect(out).toContain("Reconnect");
    expect(out).toContain('role="alert"');
  });
  it("speaks Arabic", () => {
    const out = html(fb(), true);
    expect(out).toContain("إعادة ربط");
    expect(out).toContain("pages_manage_posts، read_insights");
  });
  it("shows nothing when nothing is missing, or for any other channel, or when not connected", () => {
    expect(html(fb({ missingScopes: [] }))).toBe("");
    expect(html(fb({ missingScopes: undefined }))).toBe("");
    expect(html(fb({ id: "messenger" }))).toBe("");
    expect(html(fb({ connected: false }))).toBe("");
    expect(html(null)).toBe("");
  });
  it("is the single rule the settings row uses to ask for a re-link", () => {
    expect(facebookNeedsRelink(fb())).toBe(true);
    expect(facebookNeedsRelink(fb({ missingScopes: [] }))).toBe(false);
  });
});
