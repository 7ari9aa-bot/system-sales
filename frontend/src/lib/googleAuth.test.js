import { describe, it, expect } from "vitest";
import { googleAuthorizeUrl, googleErrorMessage } from "./googleAuth";

describe("googleAuthorizeUrl", () => {
  it("is the bare link when there is nothing to carry", () => {
    expect(googleAuthorizeUrl("/dashboard", null)).toBe("/api/v1/auth/google/authorize");
  });
  it("carries the page to resume and the tracked visitor", () => {
    const url = googleAuthorizeUrl("/orders?tab=open", "v-abc12345");
    const q = new URLSearchParams(url.split("?")[1]);
    expect(q.get("returnTo")).toBe("/orders?tab=open");
    expect(q.get("visitor_id")).toBe("v-abc12345");
  });
  it("never invents a visitor id for an untracked browser", () => {
    expect(googleAuthorizeUrl("/inbox", null)).not.toContain("visitor_id");
  });
});

describe("googleErrorMessage", () => {
  it("explains each Google failure in both languages", () => {
    expect(googleErrorMessage("?error=google_mfa_required", "ar")).toContain("خطوتين");
    expect(googleErrorMessage("?error=google_mfa_required", "en")).toContain("two-step");
    expect(googleErrorMessage("?error=google_email_unverified", "en")).toContain("not verified");
  });
  it("ignores errors that are not Google's", () => {
    expect(googleErrorMessage("?error=something_else", "ar")).toBe("");
    expect(googleErrorMessage("", "ar")).toBe("");
  });
});
