import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import MetaPageChoiceDialog from "@/pages/settings/MetaPageChoiceDialog";

const choice = {
  ticket: "ticket-never-rendered",
  provider: "facebook",
  pages: [
    { id: "111", name: "Shop One" },
    { id: "222", name: "Shop Two" },
  ],
};
const html = (props = {}, isAr = false) =>
  renderToStaticMarkup(<MetaPageChoiceDialog choice={choice} isAr={isAr} onChoose={() => {}} onCancel={() => {}} {...props} />);
const tag = (out, re) => (out.match(re) || [""])[0];

describe("the Page choice dialog", () => {
  it("is a labelled dialog naming the channel", () => {
    const out = html();
    expect(out).toContain('role="dialog"');
    expect(out).toContain('aria-label="Choose the Page to connect to Facebook"');
    expect(html({ choice: { ...choice, provider: "instagram" } })).toContain("connect to Instagram");
  });

  it("lists every Page by name as a radio and pre-selects none of them", () => {
    const out = html();
    expect(out).toContain("Shop One");
    expect(out).toContain("Shop Two");
    const radios = [...out.matchAll(/<input[^>]*type="radio"[^>]*>/g)].map((m) => m[0]);
    expect(radios).toHaveLength(2);
    expect(radios.every((r) => !r.includes("checked"))).toBe(true);
  });

  it("cannot connect until a Page is chosen", () => {
    const submit = tag(html(), /<button[^>]*type="submit"[^>]*>/);
    expect(submit).toContain("disabled");
  });

  it("never prints the ticket or anything token-like", () => {
    const out = html();
    expect(out).not.toContain("ticket-never-rendered");
    expect(out).not.toMatch(/token/i);
  });

  it("locks the choices and the buttons while connecting, and says so", () => {
    const out = html({ busy: true });
    expect(out).toContain("Connecting…");
    expect(tag(out, /<fieldset[^>]*>/)).toContain("disabled");
    expect(tag(out, /<button[^>]*type="button"[^>]*>/)).toContain("disabled");
  });

  it("shows a refusal as an alert so the owner knows to press connect again", () => {
    const out = html({ error: "This choice expired. Press connect again." });
    expect(out).toContain('role="alert"');
    expect(out).toContain("This choice expired. Press connect again.");
  });

  it("speaks Arabic right to left when asked", () => {
    const out = html({}, true);
    expect(out).toContain('dir="rtl"');
    expect(out).toContain("اختر الصفحة التي تريد ربطها بـ Facebook");
    expect(out).toContain("ربط هذه الصفحة");
  });
});
