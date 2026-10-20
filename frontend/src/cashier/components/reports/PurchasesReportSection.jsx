import ReportTable from "@/cashier/components/reports/ReportTable";
import { CELL_ACCENT, CELL_EMPTY, CELL_MAIN, CELL_NUM } from "@/cashier/components/ui-kit/ledgerStyles";
import { fmtDate, fmtInt, fmtMoney } from "@/cashier/lib/format";

// تقرير المشتريات: توريدات كل مورد مع المدفوع والمتبقي.
export default function PurchasesReportSection({ rows }) {
  const sum = rows.reduce(
    (acc, r) => ({ orders: acc.orders + r.orders, pieces: acc.pieces + r.pieces, total: acc.total + r.total, paid: acc.paid + r.paid, balance: acc.balance + r.balance }),
    { orders: 0, pieces: 0, total: 0, paid: 0, balance: 0 },
  );

  const columns = [
    { key: "supplier", header: "المورد", render: (r) => <span className={`${CELL_MAIN} font-semibold`}>{r.supplier}</span> },
    { key: "orders", header: "عدد فواتير التوريد", align: "center", render: (r) => <span className={CELL_NUM}>{fmtInt(r.orders)}</span> },
    { key: "pieces", header: "القطع الموردة", align: "center", render: (r) => <span className={CELL_NUM}>{fmtInt(r.pieces)}</span> },
    { key: "total", header: "إجمالي التوريد", align: "end", render: (r) => <span className={`${CELL_NUM} font-semibold`}>{fmtMoney(r.total)}</span> },
    { key: "paid", header: "المدفوع للمورد", align: "end", render: (r) => <span className={`${CELL_NUM} text-emerald-600`}>{fmtMoney(r.paid)}</span> },
    { key: "balance", header: "المتبقي", align: "end", render: (r) => <span className={r.balance > 0 ? CELL_ACCENT : CELL_EMPTY}>{fmtMoney(r.balance)}</span> },
    { key: "lastOrder", header: "آخر توريد", align: "center", render: (r) => <span className={`${CELL_NUM} text-[#7A766C]`}>{r.lastOrder ? fmtDate(r.lastOrder) : "—"}</span> },
  ];

  const totals = {
    supplier: "الإجمالي",
    orders: fmtInt(sum.orders),
    pieces: fmtInt(sum.pieces),
    total: fmtMoney(sum.total),
    paid: fmtMoney(sum.paid),
    balance: fmtMoney(sum.balance),
  };

  return (
    <ReportTable
      title="تقرير المشتريات"
      description="توريدات كل مورد: عدد الفواتير، القطع، القيمة، المدفوع والمتبقي"
      columns={columns}
      rows={rows}
      totals={totals}
      footnote={`إجمالي التوريدات: ${fmtMoney(sum.total)} • المدفوع: ${fmtMoney(sum.paid)} • المستحق للموردين: ${fmtMoney(sum.balance)}`}
    />
  );
}