import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import DataTable from "./DataTable";

const columns = [
  { key: "number", header: "رقم الوردية" },
  { key: "employee", header: "الموظف" },
  { key: "total", header: "الإجمالي" },
];
const rows = [{ id: "1", number: "7", employee: "منى", total: "300.00" }];

const render = (props) => renderToStaticMarkup(<DataTable columns={columns} rows={[]} {...props} />);

describe("a ledger that is still loading", () => {
  const html = render({ loading: true, loadingLabel: "جارٍ تحميل الورديات…" });

  it("shows a skeleton table instead of the bare loading line", () => {
    expect(html).toContain('data-testid="data-table-loading"');
    expect(html).toContain("animate-pulse");
    expect(html).not.toContain("جارٍ التحميل…");
  });

  it("keeps the real column headers so the layout does not jump", () => {
    expect(html).toContain("رقم الوردية");
    expect(html).toContain("الموظف");
    expect(html).toContain("الإجمالي");
  });

  it("announces itself once to screen readers", () => {
    expect(html).toContain('role="status"');
    expect(html).toContain('aria-busy="true"');
    expect(html).toContain("جارٍ تحميل الورديات…");
  });

  it("draws no data rows while loading", () => {
    expect(html).not.toContain("منى");
  });
});

describe("a ledger that finished loading empty", () => {
  const html = render({ loading: false, emptyTitle: "لا توجد ورديات مطابقة" });

  it("shows the empty state, not a skeleton", () => {
    expect(html).toContain("لا توجد ورديات مطابقة");
    expect(html).not.toContain('data-testid="data-table-loading"');
  });
});

describe("a ledger with rows", () => {
  it("ignores the loading flag once data is there", () => {
    const html = renderToStaticMarkup(<DataTable columns={columns} rows={rows} loading />);
    expect(html).toContain("منى");
    expect(html).not.toContain('data-testid="data-table-loading"');
  });
});
