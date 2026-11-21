import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import ProfitReportSection from "./ProfitReportSection";
import ProfitFilters from "./ProfitFilters";

const row = (over = {}) => ({
  id: "v1",
  model: "جينز سليم",
  season: "AW26",
  brandId: "b1",
  size: "32",
  colour: "أزرق",
  unitsSold: 10,
  unitsReturned: 0,
  revenue: 1000,
  cost: 600,
  profit: 400,
  margin: 40,
  unitsWithoutCost: 0,
  costIsEstimate: false,
  ...over,
});

const totalsOf = (rows) => ({
  unitsSold: rows.reduce((s, r) => s + r.unitsSold, 0),
  revenue: rows.reduce((s, r) => s + r.revenue, 0),
  cost: rows.reduce((s, r) => s + r.cost, 0),
  profit: rows.reduce((s, r) => s + r.profit, 0),
  margin: 40,
  unitsWithoutCost: rows.reduce((s, r) => s + r.unitsWithoutCost, 0),
  costIsComplete: rows.every((r) => r.unitsWithoutCost === 0),
});

const draw = (rows, totals = totalsOf(rows)) =>
  renderToStaticMarkup(<ProfitReportSection rows={rows} totals={totals} />);

describe("the profit report as drawn", () => {
  it("shows a row with its model, colour, size, revenue, cost, profit and margin", () => {
    const html = draw([row()]);
    expect(html).toContain("جينز سليم");
    expect(html).toContain("أزرق / 32");
    expect(html).toContain("AW26");
    expect(html).toContain("1,000.00");
    expect(html).toContain("600.00");
    expect(html).toContain("400.00");
    expect(html).toContain("40.0٪");
  });

  it("shows a loss-making item with its minus sign, in red, without crashing", () => {
    const html = draw([row({ revenue: 100, cost: 150, profit: -50, margin: -50 })]);
    expect(html).toContain("-50.00");
    expect(html).toContain("-50.0٪");
    expect(html).toContain("text-rose-600");
  });

  it("does not paint a profitable row red", () => {
    expect(draw([row()])).not.toContain("text-rose-600");
  });

  it("says the table is empty instead of drawing a broken one", () => {
    const html = draw([], null);
    expect(html).toContain("مفيش مبيعات في الفترة");
    expect(html).toContain('role="status"');
    expect(html).not.toContain("الإجمالي");
  });

  it("warns that the profit may be too high when a sold piece had no cost", () => {
    const rows = [row({ unitsWithoutCost: 2 })];
    const html = draw(rows, { ...totalsOf(rows), unitsWithoutCost: 2, costIsComplete: false });
    expect(html).toContain("ربح أعلى من الحقيقة");
    expect(html).toContain("2");
    expect(html).toContain('role="alert"');
  });

  it("shows no warning when every piece had a real cost", () => {
    const html = draw([row()]);
    expect(html).not.toContain("ربح أعلى من الحقيقة");
  });

  it("marks a row whose returned cost is an estimate, and explains the mark", () => {
    const html = draw([row({ costIsEstimate: true, unitsReturned: 1 })]);
    expect(html).toContain("≈");
    expect(html).toContain("تكلفة تقديرية");
    expect(html).toContain("مرتجع 1");
  });

  it("puts the totals row under the table", () => {
    const rows = [row(), row({ id: "v2", profit: 100, revenue: 200, cost: 100 })];
    const html = draw(rows);
    expect(html).toContain("الإجمالي");
    expect(html).toContain("1,200.00");
    expect(html).toContain("700.00");
    expect(html).toContain("500.00");
  });

  it("survives rows and totals that arrive before the data does", () => {
    expect(() => renderToStaticMarkup(<ProfitReportSection />)).not.toThrow();
    expect(() => renderToStaticMarkup(<ProfitReportSection rows={null} totals={null} />)).not.toThrow();
  });
});

describe("the profit filters", () => {
  // Radix Select does not render its options in static markup, so the props are what is checked:
  // what the panel is HANDED is what it will show once it opens.
  function collect(node, found = []) {
    if (Array.isArray(node)) node.forEach((n) => collect(n, found));
    else if (node && typeof node === "object" && node.props) {
      found.push(node);
      collect(node.props.children, found);
    }
    return found;
  }

  const empty = { brand: "", season: "" };
  const brands = [{ id: "b1", name: "نيل" }, { id: "b2", name: "دلتا" }];
  const seasons = ["AW26", "SS26"];

  // onChange is passed through: a render with a no-op handler would swallow the very call the
  // "keeps the other filter" test is trying to observe.
  const picks = (values, onChange = () => {}) =>
    collect(ProfitFilters({ values, onChange, brands, seasons }).props.children).filter((n) => n.props?.allLabel);

  it("offers a brand and a season filter, each with its Arabic label", () => {
    const html = renderToStaticMarkup(<ProfitFilters values={empty} onChange={() => {}} brands={brands} seasons={seasons} />);
    expect(html).toContain("العلامة التجارية");
    expect(html).toContain("الموسم");
  });

  it("tells each box what 'all' is called", () => {
    expect(picks(empty).map((n) => n.props.allLabel)).toEqual(["كل العلامات", "كل المواسم"]);
  });

  it("hands each box the chosen value and the real brand names", () => {
    const found = picks({ brand: "b2", season: "SS26" });
    const brandPick = found.find((n) => n.props.label === "العلامة التجارية").props;
    expect(brandPick.value).toBe("b2");
    expect(brandPick.options.find((o) => o.value === "b2").label).toBe("دلتا");
    expect(found.find((n) => n.props.label === "الموسم").props.value).toBe("SS26");
  });

  it("counts the filters in use", () => {
    const html = (values) => renderToStaticMarkup(<ProfitFilters values={values} onChange={() => {}} brands={brands} seasons={seasons} />);
    expect(html(empty)).not.toMatch(/num rounded-full/);
    expect(html({ brand: "b1", season: "" })).toMatch(/num rounded-full[^>]*>1</);
    expect(html({ brand: "b1", season: "AW26" })).toMatch(/num rounded-full[^>]*>2</);
  });

  it("clears both filters on reset, and keeps the other one when one changes", () => {
    let got = null;
    const onChange = (v) => {
      got = v;
    };
    const panel = ProfitFilters({ values: { brand: "b1", season: "AW26" }, onChange, brands, seasons });
    // FilterPanel is the root: its onReset and each Pick's onChange are the two ways values move.
    expect(panel.props.onReset).toBeTypeOf("function");
    panel.props.onReset();
    expect(got).toEqual({ brand: "", season: "" });

    const seasonPick = picks({ brand: "b1", season: "AW26" }, onChange).find((n) => n.props.label === "الموسم");
    seasonPick.props.onChange("SS26");
    expect(got).toEqual({ brand: "b1", season: "SS26" });
  });

  it("works before the brand and season lists have loaded", () => {
    expect(() => renderToStaticMarkup(<ProfitFilters values={empty} onChange={() => {}} />)).not.toThrow();
  });
});
