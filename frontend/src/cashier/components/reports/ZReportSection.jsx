import { Printer } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import ReportTable from "@/cashier/components/reports/ReportTable";
import { CELL_ACCENT, CELL_MAIN, CELL_NUM } from "@/cashier/components/ui-kit/ledgerStyles";
import { SHIFT_STATUS, fmtDate, fmtInt, fmtMoney, fmtTime } from "@/cashier/lib/format";

// تقرير Z (إغلاق اليوم): ملخص كل وردية في صف واحد ثم تسوية النقدية.
// النقدية المتوقعة = رصيد البداية + مبيعات نقدي − مرتجعات نقدي − مصروفات نقدي (نفس معادلة شاشة الورديات).
export default function ZReportSection({ rows }) {
  const sum = (key) => +rows.reduce((s, r) => s + (r[key] ?? 0), 0).toFixed(2);
  const closed = rows.filter((r) => r.status === "closed");
  const open = rows.filter((r) => r.status === "open");

  const totals = {
    invoices: sum("invoices"),
    cashSales: sum("cashSales"),
    cardSales: sum("cardSales"),
    walletSales: sum("walletSales"),
    creditSales: sum("creditSales"),
    returnsCash: sum("returnsCash"),
    expensesCash: sum("expensesCash"),
    expected: sum("expected"),
    difference: +closed.reduce((s, r) => s + r.difference, 0).toFixed(2),
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
    { key: "cashSales", header: "مبيعات نقدي", align: "end", render: (r) => <span className={CELL_NUM}>{fmtMoney(r.cashSales)}</span> },
    { key: "cardSales", header: "بطاقة", align: "end", render: (r) => <span className={CELL_NUM}>{fmtMoney(r.cardSales)}</span> },
    { key: "walletSales", header: "محفظة", align: "end", render: (r) => <span className={CELL_NUM}>{fmtMoney(r.walletSales)}</span> },
    { key: "creditSales", header: "آجل", align: "end", render: (r) => <span className={CELL_NUM}>{fmtMoney(r.creditSales)}</span> },
    { key: "returnsCash", header: "مرتجعات نقدي", align: "end", render: (r) => <span className={`${CELL_NUM} text-rose-600`}>{fmtMoney(r.returnsCash)}</span> },
    { key: "expensesCash", header: "مصروفات نقدي", align: "end", render: (r) => <span className={`${CELL_NUM} text-rose-600`}>{fmtMoney(r.expensesCash)}</span> },
    { key: "expected", header: "المتوقع في الدرج", align: "end", render: (r) => <span className={CELL_ACCENT}>{fmtMoney(r.expected)}</span> },
    {
      key: "difference",
      header: "الفرق عند العدّ",
      align: "end",
      render: (r) =>
        r.status === "open" ? (
          <span className="text-[12px] text-[#7A766C]">لم تُغلق</span>
        ) : (
          <span className={`${CELL_NUM} ${r.difference === 0 ? "text-emerald-600" : r.difference > 0 ? "text-amber-600" : "text-rose-600"}`}>
            {r.difference === 0 ? "مطابقة" : `${r.difference > 0 ? "+" : ""}${fmtMoney(r.difference)}`}
          </span>
        ),
    },
  ];

  const footTotals = {
    number: "الإجمالي",
    invoices: fmtInt(totals.invoices),
    cashSales: fmtMoney(totals.cashSales),
    cardSales: fmtMoney(totals.cardSales),
    walletSales: fmtMoney(totals.walletSales),
    creditSales: fmtMoney(totals.creditSales),
    returnsCash: fmtMoney(totals.returnsCash),
    expensesCash: fmtMoney(totals.expensesCash),
    expected: fmtMoney(totals.expected),
    difference: closed.length ? fmtMoney(totals.difference) : "—",
  };

  return (
    <div className="space-y-0">
      <div className="flex items-center justify-between border border-b-0 border-[#DED8CD] bg-white px-3.5 py-2 print:hidden">
        <p className="text-[11px] text-[#7A766C]">
          {open.length > 0
            ? `يوجد ${fmtInt(open.length)} وردية مفتوحة: أرقامها مبدئية حتى تُغلق.`
            : "كل الورديات في الفترة مغلقة."}
        </p>
        <Button variant="outline" size="sm" className="h-7 gap-1.5 text-[11px]" onClick={() => window.print()}>
          <Printer className="h-3.5 w-3.5" />
          طباعة التقرير
        </Button>
      </div>

      <ReportTable
        title="تقرير Z — إغلاق الورديات"
        description="لكل وردية: المبيعات حسب طريقة الدفع، النقدية الخارجة، والمتوقع في الدرج مقابل المعدود"
        columns={columns}
        rows={rows}
        totals={footTotals}
        footnote={`الورديات: ${fmtInt(rows.length)} • المغلقة: ${fmtInt(closed.length)} • المبيعات غير النقدية (بطاقة + محفظة + آجل): ${fmtMoney(
          totals.cardSales + totals.walletSales + totals.creditSales,
        )}`}
      />
    </div>
  );
}
