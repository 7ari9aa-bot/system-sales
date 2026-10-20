import ReportTable from "@/cashier/components/reports/ReportTable";
import { CELL_MAIN, CELL_NUM } from "@/cashier/components/ui-kit/ledgerStyles";
import { fmtInt, fmtMoney } from "@/cashier/lib/format";

// تقرير المرتجعات: تجميع حسب سبب الإرجاع مع القطع والمبالغ ونسبة كل سبب.
export default function ReturnsReportSection({ rows }) {
  const sum = rows.reduce((acc, r) => ({ count: acc.count + r.count, qty: acc.qty + r.qty, amount: acc.amount + r.amount }), {
    count: 0,
    qty: 0,
    amount: 0,
  });

  const columns = [
    { key: "reason", header: "سبب الإرجاع", render: (r) => <span className={`${CELL_MAIN} font-semibold`}>{r.reason}</span> },
    { key: "count", header: "عدد العمليات", align: "center", render: (r) => <span className={CELL_NUM}>{fmtInt(r.count)}</span> },
    { key: "qty", header: "القطع المرتجعة", align: "center", render: (r) => <span className={CELL_NUM}>{fmtInt(r.qty)}</span> },
    { key: "invoices", header: "فواتير مرتبطة", align: "center", render: (r) => <span className={CELL_NUM}>{fmtInt(r.invoices)}</span> },
    { key: "average", header: "متوسط قيمة العملية", align: "end", render: (r) => <span className={CELL_NUM}>{fmtMoney(r.average)}</span> },
    { key: "amount", header: "إجمالي المبالغ", align: "end", render: (r) => <span className={`${CELL_NUM} font-semibold text-rose-600`}>{fmtMoney(r.amount)}</span> },
    { key: "share", header: "النسبة من الإجمالي", align: "center", render: (r) => <span className={CELL_NUM}>{r.share}%</span> },
  ];

  const totals = {
    reason: "الإجمالي",
    count: fmtInt(sum.count),
    qty: fmtInt(sum.qty),
    invoices: "",
    average: fmtMoney(sum.count ? sum.amount / sum.count : 0),
    amount: fmtMoney(sum.amount),
    share: "",
  };

  return (
    <ReportTable
      title="تقرير المرتجعات"
      description="المرتجعات مجمّعة حسب السبب — كم قطعة رجعت وكم كلّفت المحل"
      columns={columns}
      rows={rows}
      totals={totals}
      footnote={`${fmtInt(sum.count)} عملية إرجاع • ${fmtInt(sum.qty)} قطعة • ${fmtMoney(sum.amount)}`}
    />
  );
}