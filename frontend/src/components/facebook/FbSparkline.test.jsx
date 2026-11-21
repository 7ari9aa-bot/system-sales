import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import FbSparkline from "@/components/facebook/FbSparkline";

const days = [
  { day: "2026-11-01", value: 2 },
  { day: "2026-11-02", value: 9 },
  { day: "2026-11-03", value: 5 },
];
const html = (props) => renderToStaticMarkup(<FbSparkline series={days} lang="en" label="Content views" {...props} />);

describe("the insights sparkline", () => {
  it("is an image with a text description a screen reader can use", () => {
    const out = html();
    expect(out).toContain('role="img"');
    expect(out).toMatch(/aria-label="Content views: 3 days, from 2 to 5, highest 9"/);
  });
  it("draws the line and the filled area", () => {
    const out = html();
    expect(out).toMatch(/<path[^>]*d="M0,/);
    expect((out.match(/<path/g) || []).length).toBe(2);
  });
  it("has a point for each day that names the day and its number", () => {
    const out = html();
    expect((out.match(/<circle/g) || []).length).toBe(3);
    expect(out).toContain("2026-11-02: 9");
  });
  it("describes itself in Arabic", () => {
    expect(html({ lang: "ar", label: "المشاهدات" })).toContain('aria-label="المشاهدات: 3 أيام');
  });
  it("draws nothing for a single empty series", () => {
    expect(html({ series: [] })).toBe("");
  });
});
