import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import SalesLogTable from "./SalesLogTable";

const columns = [
  { key: "number", header: "رقم الفاتورة" },
  { key: "pieces", header: "القطع" },
  { key: "total", header: "الإجمالي" },
];

describe("the sales log before the invoices arrive", () => {
  const html = renderToStaticMarkup(
    <SalesLogTable columns={columns} rows={[]} loading loadingLabel="جارٍ تحميل فواتير الوردية…" />,
  );

  it("shows a skeleton table instead of the empty state", () => {
    expect(html).toContain('data-testid="sales-log-loading"');
    expect(html).toContain("animate-pulse");
    expect(html).not.toContain("لا توجد فواتير مطابقة للفلاتر");
  });

  it("keeps the headers and the accessible label", () => {
    expect(html).toContain("رقم الفاتورة");
    expect(html).toContain("جارٍ تحميل فواتير الوردية…");
    expect(html).toContain('role="status"');
  });
});

describe("the sales log after loading", () => {
  it("shows the empty state when there is nothing to show", () => {
    const html = renderToStaticMarkup(<SalesLogTable columns={columns} rows={[]} emptyTitle="لا توجد فواتير مطابقة للفلاتر" />);
    expect(html).toContain("لا توجد فواتير مطابقة للفلاتر");
    expect(html).not.toContain('data-testid="sales-log-loading"');
  });
});
