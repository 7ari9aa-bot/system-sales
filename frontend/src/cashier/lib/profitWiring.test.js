import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// The reports page is JSX the test setup cannot render, so the wiring that carries the period, the
// brand and the season from the screen to the server is guarded at the source: a broken link here
// shows the owner a profit for the wrong window, or for every brand while one is selected.
const read = (rel) => readFileSync(new URL(`../${rel}`, import.meta.url), "utf8");

describe("the profit tab is on the reports page and asks for what the owner picked", () => {
  const page = read("routes/_authed/reports.jsx");

  it("the tab is registered, labelled in Arabic, and has its content", () => {
    expect(page).toMatch(/\{ key: "profit", label: "الربح" \}/);
    expect(page).toMatch(/<TabsContent value="profit"/);
  });

  it("the report is asked for only while its tab is open, so a cashier never triggers a refused request", () => {
    expect(page).toMatch(/enabled: tab === "profit"/);
  });

  it("the period, brand and season on screen are the ones sent", () => {
    const call = page.match(/useProfitReport\(\{[\s\S]*?\}\)/)?.[0] ?? "";
    expect(call).toMatch(/\bperiod,/);
    expect(call).toMatch(/brandId: profitFilters\.brand,/);
    expect(call).toMatch(/season: profitFilters\.season,/);
  });

  it("the filters start empty (every brand, every season) and are what the filter box edits", () => {
    expect(page).toMatch(/useState\(\{ brand: "", season: "" \}\)/);
    expect(page).toMatch(/<ProfitFilters\s+values=\{profitFilters\}\s+onChange=\{setProfitFilters\}/);
  });

  it("a refused or failed request shows its notice instead of a table, and the table gets the rows and totals", () => {
    expect(page).toMatch(/profitErrorNotice\(profitQueryResult\.error\)/);
    expect(page).toMatch(/rows=\{profitQueryResult\.data\?\.rows \?\? \[\]\}/);
    expect(page).toMatch(/totals=\{profitQueryResult\.data\?\.totals \?\? null\}/);
  });

  it("the other tabs are still there", () => {
    for (const key of ["sales", "products", "inventory", "zreport"]) {
      expect(page).toMatch(new RegExp(`\\{ key: "${key}"`));
    }
  });
});
