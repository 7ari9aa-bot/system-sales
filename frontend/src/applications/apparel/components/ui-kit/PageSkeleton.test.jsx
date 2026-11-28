import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import PageSkeleton from "./PageSkeleton";

describe("a cashier page while it loads", () => {
  const html = renderToStaticMarkup(<PageSkeleton rows={4} />);

  it("draws a page shape instead of one bare loading sentence", () => {
    expect(html).toContain('data-testid="cashier-page-loading"');
    expect(html).toContain("animate-pulse");
    expect(html).not.toContain("جارٍ التحميل…</div>");
  });

  it("repeats the row shape as many times as asked", () => {
    const rows = html.split("border-t border-border/70").length - 1;
    expect(rows).toBe(4);
  });

  it("announces the wait once and keeps the shapes decorative", () => {
    expect(html).toContain('role="status"');
    expect(html).toContain('aria-busy="true"');
    expect(html).toContain("sr-only");
    expect(html).toContain('aria-hidden="true"');
  });
});
