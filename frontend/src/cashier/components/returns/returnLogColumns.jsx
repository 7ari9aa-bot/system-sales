import { Link } from "react-router-dom";
import { CELL_ACCENT, CELL_MAIN, CELL_NUM, CELL_SUB, TD, TH } from "@/cashier/components/ui-kit/ledgerStyles";
import { fmtDateTime, fmtInt, fmtMoney } from "@/cashier/lib/format";

// أعمدة سجل المرتجعات: ما يسجله الخادم فقط (الرقم والتاريخ، الفاتورة الأصلية، الكمية، القيمة).
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
        <Link to={`/cashier/sales/${r.saleReceiptId ?? ""}?shift=${encodeURIComponent(r.sessionId ?? "")}`} className="num text-[12px] font-semibold text-[#E8761A] hover:underline">
          {r.invoiceNumber}
        </Link>
      ),
    },
    { key: "qty", header: "الكمية", headerClassName: TH, className: TD, align: "center", render: (r) => <span className={`${CELL_NUM} font-semibold`}>{fmtInt(r.qty)}</span> },
    { key: "amount", header: "قيمة المرتجع", headerClassName: TH, className: TD, align: "end", render: (r) => <span className={`${CELL_ACCENT} font-bold`}>{fmtMoney(r.amount)}</span> },
  ];
}