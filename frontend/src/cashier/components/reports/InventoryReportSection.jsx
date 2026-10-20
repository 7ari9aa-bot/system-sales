import ReportTable from "@/cashier/components/reports/ReportTable";
import { CELL_MAIN, CELL_NUM } from "@/cashier/components/ui-kit/ledgerStyles";
import { fmtInt, fmtMoney } from "@/cashier/lib/format";

// تقرير تقييم المخزون: قيمة الأرصدة الحالية بتكلفتها وبسعر بيعها.
export default function InventoryReportSection({ rows }) {
  const sum = rows.reduce(
    (acc, r) => ({ items: acc.items + r.items, variants: acc.variants + r.variants, pieces: acc.pieces + r.pieces, cost: acc.cost + r.cost, retail: acc.retail + r.retail }),
    { items: 0, variants: 0, pieces: 0, cost: 0, retail: 0 },
  );

  const columns = [
    { key: "category", header: "التصنيف", render: (r) => <span className={`${CELL_MAIN} font-semibold`}>{r.category}</span> },
    { key: "items", header: "عدد الأصناف", align: "center", render: (r) => <span className={CELL_NUM}>{fmtInt(r.items)}</span> },
    { key: "variants", header: "لون / مقاس", align: "center", render: (r) => <span className={CELL_NUM}>{fmtInt(r.variants)}</span> },
    { key: "pieces", header: "القطع المتوفرة", align: "center", render: (r) => <span className={CELL_NUM}>{fmtInt(r.pieces)}</span> },
    { key: "cost", header: "قيمة التكلفة", align: "end", render: (r) => <span className={`${CELL_NUM} text-[#7A766C]`}>{fmtMoney(r.cost)}</span> },
    { key: "retail", header: "قيمة البيع المتوقعة", align: "end", render: (r) => <span className={`${CELL_NUM} font-semibold`}>{fmtMoney(r.retail)}</span> },
    { key: "margin", header: "هامش الربح", align: "center", render: (r) => <span className={CELL_NUM}>{r.margin}%</span> },
  ];

  const totals = {
    category: "الإجمالي",
    items: fmtInt(sum.items),
    variants: fmtInt(sum.variants),
    pieces: fmtInt(sum.pieces),
    cost: fmtMoney(sum.cost),
    retail: fmtMoney(sum.retail),
    margin: `${sum.retail ? ((1 - sum.cost / sum.retail) * 100).toFixed(1) : 0}%`,
  };

  return (
    <ReportTable
      title="تقييم المخزون"
      description="قيمة الأرصدة المتوفرة حاليًا بالتكلفة وبسعر البيع"
      columns={columns}
      rows={rows}
      totals={totals}
    />
  );
}