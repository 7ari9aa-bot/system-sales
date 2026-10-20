import { Link } from "react-router-dom";
import StatusBadge from "@/cashier/components/ui-kit/StatusBadge";
import { CELL_MAIN, CELL_NUM, CELL_SUB, TD, TH } from "@/cashier/components/ui-kit/ledgerStyles";
import { fmtDateTime, fmtMoney } from "@/cashier/lib/format";
import { settlementOf } from "@/cashier/lib/opsData";

// أعمدة سجل الاستبدال: الرقم والتاريخ، الفاتورة الأصلية، العميل، الصنف المرتجع، البديل، قيمتيهما، الفرق، التسوية، الموظف، والحالة.
export default function exchangeLogColumns() {
  return [
    {
      key: "number",
      header: "رقم الاستبدال",
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
    { key: "returnedItem", header: "الصنف المرتجع", headerClassName: TH, className: TD, render: (r) => <span className={CELL_SUB}>{r.returnedItem}</span> },
    { key: "newItem", header: "الصنف البديل", headerClassName: TH, className: TD, render: (r) => <span className={`${CELL_MAIN} font-medium`}>{r.newItem}</span> },
    { key: "returnedValue", header: "قيمة المستبدل", headerClassName: TH, className: TD, align: "end", render: (r) => <span className={CELL_NUM}>{fmtMoney(r.returnedValue)}</span> },
    { key: "newValue", header: "قيمة البديل", headerClassName: TH, className: TD, align: "end", render: (r) => <span className={CELL_NUM}>{fmtMoney(r.newValue)}</span> },
    {
      key: "difference",
      header: "الفرق",
      headerClassName: TH,
      className: TD,
      align: "end",
      render: (r) => {
        const { difference } = settlementOf(r);
        const tone = difference > 0 ? "text-emerald-600" : difference < 0 ? "text-rose-600" : "text-[#33322E]";
        const sign = difference > 0 ? `+${fmtMoney(difference)}` : difference < 0 ? `-${fmtMoney(Math.abs(difference))}` : fmtMoney(0);
        return <span className={`num font-bold ${tone}`}>{sign}</span>;
      },
    },
    { key: "settlement", header: "التسوية", headerClassName: TH, className: TD, render: (r) => <StatusBadge kind="settlement" value={settlementOf(r).kind} /> },
    { key: "employee", header: "الموظف", headerClassName: TH, className: TD, render: (r) => <span className={CELL_SUB}>{r.employee}</span> },
    { key: "status", header: "الحالة", headerClassName: TH, className: TD, render: (r) => <StatusBadge kind="exchange" value={r.status} /> },
  ];
}