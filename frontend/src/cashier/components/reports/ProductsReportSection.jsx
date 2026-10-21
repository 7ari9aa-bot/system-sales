import ReportTable from "@/cashier/components/reports/ReportTable";
import { CELL_MAIN, CELL_NUM, CELL_SUB } from "@/cashier/components/ui-kit/ledgerStyles";
import { summarizeTopProducts } from "@/cashier/api/salesReport";
import { fmtInt, fmtMoney } from "@/cashier/lib/format";

// الأصناف الأكثر مبيعًا: مرتّبة بصافي الإيراد بعد خصم المرتجعات في الفترة نفسها.
// لا تكلفة ولا ربح هنا عمدًا: بند الفاتورة لا يحفظ التكلفة وقت البيع، وأي ربح يُحسب من تكلفة اليوم تخمين.
export default function ProductsReportSection({ rows }) {
  const sum = summarizeTopProducts(rows);

  const columns = [
    { key: "rank", header: "#", align: "center", render: (r) => <span className={CELL_SUB}>{fmtInt(r.rank)}</span> },
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
    { key: "sold", header: "المباع", align: "center", render: (r) => <span className={CELL_NUM}>{fmtInt(r.sold)}</span> },
    { key: "returned", header: "المرتجع", align: "center", render: (r) => <span className={`${CELL_NUM} ${r.returned ? "text-rose-600" : "text-[#7A766C]"}`}>{r.returned ? fmtInt(r.returned) : "—"}</span> },
    { key: "qty", header: "الصافي (قطع)", align: "center", render: (r) => <span className={`${CELL_NUM} font-semibold`}>{fmtInt(r.qty)}</span> },
    { key: "revenue", header: "صافي الإيراد", align: "end", render: (r) => <span className={`${CELL_NUM} font-semibold`}>{fmtMoney(r.revenue)}</span> },
  ];

  const totals = {
    rank: "",
    name: "الإجمالي",
    sold: fmtInt(sum.sold),
    returned: sum.returned ? fmtInt(sum.returned) : "—",
    qty: fmtInt(sum.qty),
    revenue: fmtMoney(sum.revenue),
  };

  return (
    <ReportTable
      title="الأصناف الأكثر مبيعًا"
      description="الأعلى إيرادًا في الفترة بعد خصم ما رجع منها. أعلى ٢٠ صنفًا."
      columns={columns}
      rows={rows}
      totals={totals}
    />
  );
}
