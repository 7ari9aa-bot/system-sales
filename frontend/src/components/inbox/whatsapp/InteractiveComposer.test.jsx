import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import InteractiveComposer from "./InteractiveComposer";

const r = (props) => renderToStaticMarkup(<InteractiveComposer open lang="en" onClose={() => {}} onSend={async () => true} {...props} />);

describe("the interactive composer when rendered", () => {
  test("renders nothing while closed", () => {
    expect(r({ open: false })).toBe("");
  });
  test("outside the 24-hour window it says so and the send button is off", () => {
    const out = r({ windowOpen: false });
    expect(out).toContain('data-testid="interactive-outside"');
    expect(out).toMatch(/data-testid="interactive-send"[^>]*disabled=""|disabled=""[^>]*data-testid="interactive-send"/);
  });
  test("inside the window there is no warning and the button is on", () => {
    const out = r({ windowOpen: true });
    expect(out).not.toContain("interactive-outside");
    expect(out).not.toMatch(/data-testid="interactive-send"[^>]*disabled=""/);
  });
  test("a send error from above is shown in the dialog, where the agent is looking", () => {
    expect(r({ sendError: "Meta says no" })).toContain("Meta says no");
    expect(r({ sendError: "" })).not.toContain("interactive-send-error");
  });
  test("the three kinds are offered and reply buttons is the default", () => {
    const out = r({});
    for (const k of ["buttons", "list", "cta_url"]) expect(out).toContain(`data-testid="kind-${k}"`);
    expect(out).toMatch(/aria-checked="true"[^>]*data-testid="kind-buttons"/);
  });
  test("it follows the language direction", () => {
    expect(r({ lang: "ar" })).toContain('dir="rtl"');
    expect(r({ lang: "en" })).toContain('dir="ltr"');
  });
});
