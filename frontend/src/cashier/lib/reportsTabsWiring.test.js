import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// The reports page and its sections are JSX the test setup cannot render, so the links that carry
// what the owner picked to the server, and the server's answer back to the table, are guarded at
// the source (the same way profitWiring.test.js guards the profit tab).
const read = (rel) => readFileSync(new URL(`../${rel}`, import.meta.url), "utf8");
const page = read("routes/_authed/reports.jsx");

describe("the sell-through tab", () => {
  it("is registered, labelled in Arabic, and has its content", () => {
    expect(page).toMatch(/\{ key: "sellthrough", label: "التصريف" \}/);
    expect(page).toMatch(/<TabsContent value="sellthrough"/);
  });
  it("asks the server only while its tab is open, so a cashier never triggers a refused request", () => {
    expect(page).toMatch(/enabled: tab === "sellthrough"/);
  });
  it("sends the period, brand, season and material on screen", () => {
    const call = page.match(/useSellThrough\(\{[\s\S]*?\}\)/)?.[0] ?? "";
    expect(call).toMatch(/\bperiod,/);
    expect(call).toMatch(/brandId: profitFilters\.brand,/);
    expect(call).toMatch(/season: profitFilters\.season,/);
    expect(call).toMatch(/material: profitFilters\.material,/);
  });
  it("shares the profit tab's filter box and gives it the shop's own lists", () => {
    const tab = page.split('<TabsContent value="sellthrough"')[1]?.split("</TabsContent>")[0] ?? "";
    expect(tab).toMatch(/<ProfitFilters\s+values=\{profitFilters\}\s+onChange=\{setProfitFilters\}/);
    expect(tab).toMatch(/materials=\{materialsQuery\.data \?\? \[\]\}/);
  });
  it("a refused or failed request shows its notice instead of a table, and the table gets rows and totals", () => {
    expect(page).toMatch(/sellThroughErrorNotice\(sellThroughResult\.error, errorKind\(sellThroughResult\.error\)\)/);
    expect(page).toMatch(/rows=\{sellThroughResult\.data\?\.rows \?\? \[\]\}/);
    expect(page).toMatch(/totals=\{sellThroughResult\.data\?\.totals \?\? null\}/);
  });
});

describe("the dead-stock tab", () => {
  it("is registered, labelled in Arabic, and has its content", () => {
    expect(page).toMatch(/\{ key: "deadstock", label: "راكد" \}/);
    expect(page).toMatch(/<TabsContent value="deadstock"/);
  });
  it("asks the server only while its tab is open", () => {
    expect(page).toMatch(/enabled: tab === "deadstock"/);
  });
  it("sends no days of its own: the window is the owner's shop setting", () => {
    const call = page.match(/useDeadStock\(\{[\s\S]*?\}\)/)?.[0] ?? "";
    expect(call).not.toMatch(/days/);
  });
  it("a refused or failed request shows its notice, and the table gets the window, rows and totals", () => {
    expect(page).toMatch(/deadStockErrorNotice\(deadStockResult\.error, errorKind\(deadStockResult\.error\)\)/);
    expect(page).toMatch(/days=\{deadStockResult\.data\?\.days \?\? null\}/);
    expect(page).toMatch(/rows=\{deadStockResult\.data\?\.rows \?\? \[\]\}/);
    expect(page).toMatch(/totals=\{deadStockResult\.data\?\.totals \?\? null\}/);
  });
});

describe("the other tabs are untouched", () => {
  it("every earlier tab is still registered, in order", () => {
    const keys = [...page.matchAll(/\{ key: "(\w+)", label:/g)].map((m) => m[1]);
    expect(keys).toEqual(["sales", "products", "inventory", "profit", "sellthrough", "deadstock", "zreport"]);
  });
});

describe("the api client reaches the two new routes", () => {
  const api = read("api/posApi.js");
  it("sell-through takes the profit query as it is", () => {
    expect(api).toMatch(/sellThrough: \(query = ""\) => api\(`\/reports\/sell-through\$\{query \? `\?\$\{query\}` : ""\}`\)/);
  });
  it("dead stock sends days only when asked, encoded", () => {
    expect(api).toMatch(/deadStock: \(days\) => api\(`\/reports\/dead-stock\$\{days \? `\?days=\$\{encodeURIComponent\(String\(days\)\)\}` : ""\}`\)/);
  });
});

describe("the sections draw what the pure modules decide", () => {
  const st = read("components/reports/SellThroughSection.jsx");
  const ds = read("components/reports/DeadStockSection.jsx");
  it("sell-through uses its columns, totals row and summary, and clamps the bar through barWidth", () => {
    expect(st).toMatch(/sellThroughColumns\(\)/);
    expect(st).toMatch(/totals=\{sellThroughTotalsRow\(totals\)\}/);
    expect(st).toMatch(/sellThroughSummary\(list\)/);
    expect(st).toMatch(/style=\{\{ width: `\$\{c\.bar\(r\)\}%` \}\}/);
  });
  it("sell-through says plainly when nothing sold and nothing is left", () => {
    expect(st).toMatch(/list\.length === 0/);
    expect(st).toMatch(/role="status"/);
  });
  it("dead stock shows the cost-gap warning only when there are rows to be wrong about", () => {
    expect(ds).toMatch(/costGapWarning\(totals\)/);
    expect(ds).toMatch(/warning && list\.length > 0/);
    expect(ds).toMatch(/role="alert"/);
  });
  it("dead stock uses its columns, totals row and header", () => {
    expect(ds).toMatch(/deadStockColumns\(\)/);
    expect(ds).toMatch(/totals=\{deadStockTotalsRow\(totals\)\}/);
    expect(ds).toMatch(/deadStockHeader\(days\)/);
  });
  it("both sections import every symbol they use from a real module", () => {
    for (const [src, names] of [
      [st, ["ReportTable", "toneClass", "sellThroughColumns", "sellThroughSummary", "sellThroughTotalsRow"]],
      [ds, ["ReportTable", "toneClass", "costGapWarning", "deadStockColumns", "deadStockHeader", "deadStockTotalsRow"]],
    ]) {
      for (const n of names) expect(src).toMatch(new RegExp(`import[^;]*\\b${n}\\b[^;]*from`));
    }
  });
  it("the page imports everything it now uses", () => {
    for (const n of ["SellThroughSection", "DeadStockSection", "useSellThrough", "useDeadStock", "errorKind", "sellThroughErrorNotice", "deadStockErrorNotice"]) {
      expect(page).toMatch(new RegExp(`import[^;]*\\b${n}\\b[^;]*from`));
    }
  });
});
