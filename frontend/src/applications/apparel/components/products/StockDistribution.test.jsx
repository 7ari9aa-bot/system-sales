import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import StockDistribution from "./StockDistribution";

const shops = [
  { id: "w-shop", name: "المحل", is_active: true },
  { id: "w-store", name: "المخزن", is_active: true },
];
const rows = [{ id: "r1", sku: "SKU-1", color: "أسود", size: "M", stock: 40, alloc: { "w-store": 30 } }];

const html = (props) => renderToStaticMarkup(<StockDistribution rows={rows} warehouses={shops} primaryId="w-shop" onChangeAllocation={() => {}} {...props} />);

describe("stock distribution section", () => {
  it("shows one input per other warehouse with the split in the shop's words", () => {
    const out = html();
    expect(out).toContain("توزيع الرصيد على مخازن تانية");
    expect(out).toContain("المخزن");
    expect(out).toContain("المحل 10 · المخزن 30");
    expect(out).toContain('value="30"');
  });

  it("stays out of the way for a shop with a single warehouse", () => {
    expect(html({ warehouses: [shops[0]] })).toBe("");
  });

  it("says nothing to distribute when every balance is zero", () => {
    expect(html({ rows: [{ ...rows[0], stock: 0 }] })).toBe("");
  });

  it("shows the refusal instead of hiding it", () => {
    expect(html({ problem: "التوزيع في أسود / M أكبر من الرصيد (55 من 40)." })).toContain("أكبر من الرصيد");
  });
});
