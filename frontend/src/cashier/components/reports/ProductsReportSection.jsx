import ReportTable from "@/cashier/components/reports/ReportTable";
import { CELL_MAIN, CELL_NUM, CELL_SUB } from "@/cashier/components/ui-kit/ledgerStyles";
import { fmtInt, fmtMoney } from "@/cashier/lib/format";

// تقرير الأصناف الأكثر مبيعًا: الكميات والإيراد والتكلفة والربح لكل صنف.
export default function ProductsReportSection({ rows }) {
  const sum = rows.reduce(
    (acc, r) => ({ qty: acc.qty + r.qty, revenue: acc.revenue + r.revenue, cost: acc.cost + r.cost, profit: acc.profit + r.profit }),
    { qty: 0, revenue: 0, cost: 0, profit: 0 },
  );

  const columns = [
    {
      key: "name",
      header: "الصنف",
      render: (r) => (
        <span>
          <span className={`block ${CELL_MAIN} font-semibold`}>{r.name}</span>
          <span className={`mt-0.5 block num ${CELL_SUB}`}>{r.sku}</span>
        </span>
      ),
    },
    { key: "category", header: "التصنيف", render: (r) => <span className={CELL_SUB}>{r.category}</span> },
    { key: "qty", header: "الكمية المباعة", align: "center", render: (r) => <span className={`${CELL_NUM} font-semibold`}>{fmtInt(r.qty)}</span> },
    { key: "revenue", header: "الإيراد", align: "end", render: (r) => <span className={CELL_NUM}>{fmtMoney(r.revenue)}</span> },
    { key: "cost", header: "التكلفة", align: "end", render: (r) => <span className={`${CELL_NUM} text-[#7A766C]`}>{fmtMoney(r.cost)}</span> },
    { key: "profit", header: "الربح", align: "end", render: (r) => <span className={`${CELL_NUM} font-semibold text-emerald-600`}>{fmtMoney(r.profit)}</span> },
    { key: "margin", header: "هامش الربح", align: "center", render: (r) => <span className={CELL_NUM}>{r.margin}%</span> },
  ];

  const totals = {
    name: "الإجمالي",
    qty: fmtInt(sum.qty),
    revenue: fmtMoney(sum.revenue),
    cost: fmtMoney(sum.cost),
    profit: fmtMoney(sum.profit),
    margin: `${sum.revenue ? ((sum.profit / sum.revenue) * 100).toFixed(1) : 0}%`,
  };

  return (
    <ReportTable
      title="الأصناف الأكثر مبيعًا"
      description="الربح محسوب من فرق سعر البيع عن سعر الشراء لكل صنف"
      columns={columns}
      rows={rows}
      totals={totals}
    />
  );
}