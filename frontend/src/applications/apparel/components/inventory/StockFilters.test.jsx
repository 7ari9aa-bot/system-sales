import { renderToStaticMarkup } from "react-dom/server";
import { isValidElement } from "react";
import { describe, expect, it } from "vitest";
import StockFilters from "./StockFilters";

const categories = [{ id: "c1", name: "قمصان" }];
const brands = [{ id: "b1", name: "نيل" }, { id: "b2", name: "دلتا" }];
const seasons = ["AW26", "SS26"];
const materials = ["قطن", "كتان"];
const empty = { term: "", category: "", brand: "", season: "", material: "", status: "" };

const draw = (values = empty, lists = {}) =>
  renderToStaticMarkup(
    <StockFilters values={values} onChange={() => {}} categories={categories} brands={brands} seasons={seasons} materials={materials} {...lists} />,
  );

// The panel is a plain function component tree: walk to the pieces and call their handlers.
function collect(node, found = []) {
  if (Array.isArray(node)) node.forEach((n) => collect(n, found));
  else if (isValidElement(node)) {
    found.push(node);
    collect(node.props?.children, found);
  }
  return found;
}

const picksOf = (nodes) => nodes.filter((n) => n.props?.allLabel);
const draw0 = () =>
  collect(StockFilters({ values: empty, onChange: () => {}, categories, brands, seasons, materials }).props.children);

describe("the stock filters", () => {
  it("offers search, category, brand, season, material and status, each with its Arabic label", () => {
    const html = draw();
    for (const label of ["بحث بالمنتج أو الكود أو الباركود", "التصنيف", "العلامة التجارية", "الموسم", "الخامة", "حالة الرصيد"]) {
      expect(html).toContain(label);
    }
  });
  it("each pick-one box is told what 'all' is called", () => {
    const labels = picksOf(draw0()).map((n) => n.props.allLabel);
    expect(labels).toEqual(["كل التصنيفات", "كل العلامات", "كل المواسم", "كل الخامات", "كل الحالات"]);
  });
  it("hands each box the value that is chosen, so the brand, season and material it shows are the chosen ones", () => {
    const nodes = collect(
      StockFilters({ values: { ...empty, brand: "b2", season: "SS26", material: "قطن" }, onChange: () => {}, categories, brands, seasons, materials })
        .props.children,
    );
    const get = (label) => picksOf(nodes).find((n) => n.props.label === label).props;
    expect(get("العلامة التجارية").value).toBe("b2");
    expect(get("الموسم").value).toBe("SS26");
    expect(get("الخامة").value).toBe("قطن");
    expect(get("التصنيف").value).toBe("");
    // and the name the owner sees for that id is the brand's name
    expect(get("العلامة التجارية").options.find((o) => o.value === "b2").label).toBe("دلتا");
  });
  it("counts the filters in use, brand, season and material included", () => {
    expect(draw()).not.toMatch(/num rounded-full/);
    expect(draw({ ...empty, brand: "b1" })).toMatch(/num rounded-full[^>]*>1</);
    expect(draw({ ...empty, brand: "b1", season: "SS26", term: "قميص", status: "low", category: "c1" })).toMatch(/num rounded-full[^>]*>5</);
    expect(draw({ ...empty, brand: "b1", season: "SS26", material: "قطن", term: "قميص", status: "low", category: "c1" })).toMatch(/num rounded-full[^>]*>6</);
  });
  it("works before the lists have loaded", () => {
    expect(() => draw(empty, { categories: undefined, brands: undefined, seasons: undefined, materials: undefined })).not.toThrow();
  });
});

describe("changing a filter", () => {
  function panel(values, onChange) {
    // StockFilters renders FilterPanel > div > [search div, Pick x5]; Pick is a function component
    const root = StockFilters({ values, onChange, categories, brands, seasons, materials });
    return collect(root.props.children);
  }
  const byLabel = (nodes, label) => picksOf(nodes).find((n) => n.props.label === label);

  it("choosing a brand changes only the brand and keeps the rest", () => {
    const seen = [];
    const nodes = panel({ ...empty, term: "قميص", season: "SS26" }, (v) => seen.push(v));
    byLabel(nodes, "العلامة التجارية").props.onChange("b1");
    expect(seen.at(-1)).toEqual({ ...empty, term: "قميص", brand: "b1", season: "SS26" });
  });
  it("choosing a season changes only the season", () => {
    const seen = [];
    const nodes = panel({ ...empty, brand: "b1" }, (v) => seen.push(v));
    byLabel(nodes, "الموسم").props.onChange("AW26");
    expect(seen.at(-1)).toEqual({ ...empty, brand: "b1", season: "AW26" });
  });
  it("choosing a material changes only the material and keeps the other filters", () => {
    const seen = [];
    const nodes = panel({ ...empty, brand: "b1", season: "SS26" }, (v) => seen.push(v));
    byLabel(nodes, "الخامة").props.onChange("قطن");
    expect(seen.at(-1)).toEqual({ ...empty, brand: "b1", season: "SS26", material: "قطن" });
  });
  it("the brand list is the shop's brands, the season list the seasons passed in", () => {
    const nodes = panel(empty, () => {});
    expect(byLabel(nodes, "العلامة التجارية").props.options).toEqual([
      { value: "b1", label: "نيل" },
      { value: "b2", label: "دلتا" },
    ]);
    expect(byLabel(nodes, "الموسم").props.options).toEqual([
      { value: "AW26", label: "AW26" },
      { value: "SS26", label: "SS26" },
    ]);
  });
  it("the material list is the shop's own materials, passed in", () => {
    expect(byLabel(panel(empty, () => {}), "الخامة").props.options).toEqual([
      { value: "قطن", label: "قطن" },
      { value: "كتان", label: "كتان" },
    ]);
  });
  it("the clear button empties every filter, brand, season and material included", () => {
    const seen = [];
    const root = StockFilters({
      values: { term: "x", category: "c1", brand: "b1", season: "SS26", material: "قطن", status: "low" },
      onChange: (v) => seen.push(v),
      categories,
      brands,
      seasons,
      materials,
    });
    root.props.onReset();
    expect(seen.at(-1)).toEqual({ term: "", category: "", brand: "", season: "", material: "", status: "" });
  });
  it("the category list is still the shop's categories", () => {
    expect(byLabel(panel(empty, () => {}), "التصنيف").props.options).toEqual([{ value: "c1", label: "قمصان" }]);
  });
});
