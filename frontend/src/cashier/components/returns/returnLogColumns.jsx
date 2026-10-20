import { Link } from "react-router-dom";
import StatusBadge from "@/cashier/components/ui-kit/StatusBadge";
import { CELL_ACCENT, CELL_MAIN, CELL_NUM, CELL_SUB, TD, TH } from "@/cashier/components/ui-kit/ledgerStyles";
import { fmtDateTime, fmtInt, fmtMoney } from "@/cashier/lib/format";

// أعمدة سجل المرتجعات: الرقم والتاريخ، الفاتورة الأصلية، العميل، الصنف، الكمية، القيمة، التسوية، السبب، الموظف، والحالة.
export default function returnLogColumns() {
  return [
    {
      key: "number",
      header: "رقم المرتجع",
      headerClassName: TH,
      className: TD,
      render: (r) => (
        <span>
          <span className="block num text-[12px] font-semibold text-[#33322E]">{r.number}</span>
          <span className={`mt-0.5 block num ${CELL_SUB}`}>{fmtDateTime(r.date)}</span>
        </span>
      ),
    },
    {
      key: "invoiceNumber",
      header: "الفاتورة الأصلية",
      headerClassName: TH,
      className: TD,
      render: (r) => (
        <Link to="/cashier/sales/$invoiceId" params={{ invoiceId: r.invoiceId }} className="num text-[12px] font-semibold text-[#E8761A] hover:underline">
          {r.invoiceNumber}
        </Link>
      ),
    },
    { key: "customer", header: "العميل", headerClassName: TH, className: TD, render: (r) => <span className={CELL_MAIN}>{r.customer}</span> },
    {
      key: "productName",
      header: "الصنف المرتجع",
      headerClassName: TH,
      className: TD,
      render: (r) => (
        <span>
          <span className={`block ${CELL_MAIN}`}>{r.productName}</span>
          <span className={`mt-0.5 block ${CELL_SUB}`}>{r.variant}</span>
        </span>
      ),
    },
    { key: "qty", header: "الكمية", headerClassName: TH, className: TD, align: "center", render: (r) => <span className={`${CELL_NUM} font-semibold`}>{fmtInt(r.qty)}</span> },
    { key: "amount", header: "قيمة المرتجع", headerClassName: TH, className: TD, align: "end", render: (r) => <span className={`${CELL_ACCENT} font-bold`}>{fmtMoney(r.amount)}</span> },
    { key: "refundMethod", header: "طريقة الاسترداد", headerClassName: TH, className: TD, render: (r) => <StatusBadge kind="refund" value={r.refundMethod} /> },
    { key: "reason", header: "السبب", headerClassName: TH, className: TD, render: (r) => <span className={CELL_SUB}>{r.reason}</span> },
    { key: "employee", header: "الموظف", headerClassName: TH, className: TD, render: (r) => <span className={CELL_SUB}>{r.employee}</span> },
    { key: "status", header: "الحالة", headerClassName: TH, className: TD, render: (r) => <StatusBadge kind="return" value={r.status} /> },
  ];
}