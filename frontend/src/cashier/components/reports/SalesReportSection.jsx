import ReportTable from "@/cashier/components/reports/ReportTable";
import { CELL_ACCENT, CELL_MAIN, CELL_NUM } from "@/cashier/components/ui-kit/ledgerStyles";
import { fmtDate, fmtInt, fmtMoney } from "@/cashier/lib/format";

const EMPTY = { invoices: 0, pieces: 0, gross: 0, discount: 0, returns: 0, net: 0 };

// تقرير المبيعات اليومية: كل يوم في صف واحد مع الخصومات والمرتجعات والصافي.
export default function SalesReportSection({ rows }) {
  const sum = rows.reduce((acc, r) => {
    const next = { ...acc };
    Object.keys(EMPTY).forEach((k) => {
      next[k] = acc[k] + r[k];
    });
    return next;
  }, EMPTY);

  const columns = [
    { key: "date", header: "التاريخ", render: (r) => <span className={CELL_MAIN}>{fmtDate(r.date)}</span> },
    { key: "invoices", header: "عدد الفواتير", align: "center", render: (r) => <span className={CELL_NUM}>{fmtInt(r.invoices)}</span> },
    { key: "pieces", header: "القطع المباعة", align: "center", render: (r) => <span className={CELL_NUM}>{fmtInt(r.pieces)}</span> },
    { key: "gross", header: "إجمالي المبيعات", align: "end", render: (r) => <span className={CELL_NUM}>{fmtMoney(r.gross)}</span> },
    { key: "discount", header: "الخصومات", align: "end", render: (r) => <span className={`${CELL_NUM} text-amber-600`}>{fmtMoney(r.discount)}</span> },
    { key: "returns", header: "المرتجعات", align: "end", render: (r) => <span className={`${CELL_NUM} text-rose-600`}>{fmtMoney(r.returns)}</span> },
    { key: "net", header: "صافي المبيعات", align: "end", render: (r) => <span className={CELL_ACCENT}>{fmtMoney(r.net)}</span> },
  ];

  const totals = {
    date: "الإجمالي",
    invoices: fmtInt(sum.invoices),
    pieces: fmtInt(sum.pieces),
    gross: fmtMoney(sum.gross),
    discount: fmtMoney(sum.discount),
    returns: fmtMoney(sum.returns),
    net: fmtMoney(sum.net),
  };

  return (
    <ReportTable
      title="تقرير المبيعات اليومية"
      description="مبيعات كل يوم بعد خصم المرتجعات المسجلة في نفس اليوم"
      columns={columns}
      rows={rows}
      totals={totals}
      footnote={`عدد الأيام: ${rows.length} • متوسط قيمة الفاتورة: ${fmtMoney(sum.invoices ? sum.net / sum.invoices : 0)}`}
    />
  );
}