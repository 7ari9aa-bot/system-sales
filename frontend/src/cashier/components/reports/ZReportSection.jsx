import { Printer } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import ReportTable from "@/cashier/components/reports/ReportTable";
import { CELL_ACCENT, CELL_MAIN, CELL_NUM } from "@/cashier/components/ui-kit/ledgerStyles";
import { SHIFT_STATUS, fmtDate, fmtInt, fmtMoney, fmtTime } from "@/cashier/lib/format";

// تقرير Z (إغلاق اليوم): ملخص كل يوم في صف واحد، يسجّل ما حدث دون جرد للدرج.
// رصيد نهاية اليوم = رصيد البداية + الفواتير − المرتجعات (يحسبه الباك إند، والاستبدال داخل الرقمين).
export default function ZReportSection({ rows }) {
  const sum = (key) => +rows.reduce((s, r) => s + (r[key] ?? 0), 0).toFixed(2);
  const closed = rows.filter((r) => r.status === "closed");
  const open = rows.filter((r) => r.status === "open");

  const totals = {
    invoices: sum("invoices"),
    salesTotal: sum("salesTotal"),
    returnsTotal: sum("returnsTotal"),
    exchangeDifference: sum("exchangeDifference"),
    closingBalance: sum("closingBalance"),
  };

  const columns = [
    {
      key: "number",
      header: "الوردية",
      render: (r) => (
        <div>
          <span className={CELL_MAIN}>{r.number}</span>
          <span className="num block text-[10.5px] text-[#7A766C]">
            {fmtDate(r.date)} • {r.employee}
          </span>
        </div>
      ),
    },
    {
      key: "status",
      header: "الحالة",
      render: (r) => (
        <span className={r.status === "open" ? "text-[12px] text-amber-600" : CELL_MAIN}>
          {SHIFT_STATUS[r.status]?.label ?? r.status}
          {r.closedAt && <span className="num block text-[10.5px] text-[#7A766C]">{fmtTime(r.closedAt)}</span>}
        </span>
      ),
    },
    { key: "invoices", header: "الفواتير", align: "center", render: (r) => <span className={CELL_NUM}>{fmtInt(r.invoices)}</span> },
    { key: "openingCash", header: "رصيد البداية", align: "end", render: (r) => <span className={CELL_NUM}>{fmtMoney(r.openingCash)}</span> },
    { key: "salesTotal", header: "إجمالي الفواتير", align: "end", render: (r) => <span className={CELL_NUM}>{fmtMoney(r.salesTotal)}</span> },
    { key: "returnsTotal", header: "المرتجعات", align: "end", render: (r) => <span className={`${CELL_NUM} text-rose-600`}>−{fmtMoney(r.returnsTotal)}</span> },
    { key: "exchangeDifference", header: "فرق الاستبدال", align: "end", render: (r) => <span className={CELL_NUM}>{fmtMoney(r.exchangeDifference)}</span> },
    { key: "closingBalance", header: "رصيد نهاية اليوم", align: "end", render: (r) => <span className={CELL_ACCENT}>{fmtMoney(r.closingBalance)}</span> },
  ];

  const footTotals = {
    number: "الإجمالي",
    invoices: fmtInt(totals.invoices),
    salesTotal: fmtMoney(totals.salesTotal),
    returnsTotal: fmtMoney(totals.returnsTotal),
    exchangeDifference: fmtMoney(totals.exchangeDifference),
    closingBalance: fmtMoney(totals.closingBalance),
  };

  return (
    <div className="space-y-0">
      <div className="flex items-center justify-between border border-b-0 border-[#DED8CD] bg-white px-3.5 py-2 print:hidden">
        <p className="text-[11px] text-[#7A766C]">
          {open.length > 0
            ? `يوجد ${fmtInt(open.length)} يوم مفتوح: أرقامه مبدئية حتى يُغلق.`
            : "كل الورديات في الفترة مغلقة."}
        </p>
        <Button variant="outline" size="sm" className="h-7 gap-1.5 text-[11px]" onClick={() => window.print()}>
          <Printer className="h-3.5 w-3.5" />
          طباعة التقرير
        </Button>
      </div>

      <ReportTable
        title="تقرير Z — إغلاق الأيام"
        description="لكل يوم: رصيد البداية، إجمالي الفواتير، المرتجعات، فرق الاستبدال، ورصيد نهاية اليوم"
        columns={columns}
        rows={rows}
        totals={footTotals}
        footnote={`الورديات: ${fmtInt(rows.length)} • المغلقة: ${fmtInt(closed.length)}`}
      />
    </div>
  );
}
