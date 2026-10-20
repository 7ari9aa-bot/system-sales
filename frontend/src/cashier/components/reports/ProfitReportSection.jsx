import ReportTable from "@/cashier/components/reports/ReportTable";
import { CELL_MAIN, CELL_NUM } from "@/cashier/components/ui-kit/ledgerStyles";
import { fmtInt, fmtMoney } from "@/cashier/lib/format";

// تقرير الأرباح حسب تصنيف المنتج.
export default function ProfitReportSection({ rows }) {
  const sum = rows.reduce(
    (acc, r) => ({ pieces: acc.pieces + r.pieces, revenue: acc.revenue + r.revenue, cost: acc.cost + r.cost, profit: acc.profit + r.profit }),
    { pieces: 0, revenue: 0, cost: 0, profit: 0 },
  );

  const columns = [
    { key: "category", header: "التصنيف", render: (r) => <span className={`${CELL_MAIN} font-semibold`}>{r.category}</span> },
    { key: "pieces", header: "القطع المباعة", align: "center", render: (r) => <span className={CELL_NUM}>{fmtInt(r.pieces)}</span> },
    { key: "revenue", header: "صافي المبيعات", align: "end", render: (r) => <span className={CELL_NUM}>{fmtMoney(r.revenue)}</span> },
    { key: "cost", header: "تكلفة المبيعات", align: "end", render: (r) => <span className={`${CELL_NUM} text-[#7A766C]`}>{fmtMoney(r.cost)}</span> },
    { key: "profit", header: "الربح الإجمالي", align: "end", render: (r) => <span className={`${CELL_NUM} font-semibold text-emerald-600`}>{fmtMoney(r.profit)}</span> },
    { key: "margin", header: "هامش الربح", align: "center", render: (r) => <span className={CELL_NUM}>{r.margin}%</span> },
  ];

  const totals = {
    category: "الإجمالي",
    pieces: fmtInt(sum.pieces),
    revenue: fmtMoney(sum.revenue),
    cost: fmtMoney(sum.cost),
    profit: fmtMoney(sum.profit),
    margin: `${sum.revenue ? ((sum.profit / sum.revenue) * 100).toFixed(1) : 0}%`,
  };

  return (
    <ReportTable
      title="الأرباح حسب التصنيف"
      description="نفس أرقام تقرير الأرباح العام موزعة على تصنيفات المنتجات"
      columns={columns}
      rows={rows}
      totals={totals}
    />
  );
}