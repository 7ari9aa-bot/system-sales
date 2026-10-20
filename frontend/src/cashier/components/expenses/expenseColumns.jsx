import { Button } from "@/cashier/components/ui/button";
import StatusBadge from "@/cashier/components/ui-kit/StatusBadge";
import { BTN, CELL_ACCENT, CELL_MAIN, CELL_SUB, TD, TH } from "@/cashier/components/ui-kit/ledgerStyles";
import { fmtDate, fmtMoney } from "@/cashier/lib/format";

// أعمدة جدول المصروفات. المصروف المسجَّل ما بيتعدّلش ولا بيتحذف: بيتلغي بسبب ويفضل ظاهر بحالة «ملغي».
export default function expenseColumns({ onVoid }) {
  return [
    {
      key: "number",
      header: "رقم المصروف",
      headerClassName: TH,
      className: TD,
      render: (e) => (
        <span>
          <span className={`block num text-[12px] font-semibold ${e.voided ? "text-[#9A968B] line-through" : "text-[#33322E]"}`}>{e.number}</span>
          <span className={`mt-0.5 block num ${CELL_SUB}`}>{fmtDate(e.date)}</span>
        </span>
      ),
    },
    { key: "category", header: "التصنيف", headerClassName: TH, className: TD, render: (e) => <span className={CELL_MAIN}>{e.category}</span> },
    {
      key: "description",
      header: "البيان",
      headerClassName: TH,
      className: TD,
      render: (e) => (
        <span>
          <span className={CELL_MAIN}>{e.description}</span>
          {e.voided && <span className={`mt-0.5 block ${CELL_SUB}`}>سبب الإلغاء: {e.voidReason || "—"}</span>}
        </span>
      ),
    },
    { key: "payment", header: "طريقة الدفع", headerClassName: TH, className: TD, render: (e) => <StatusBadge kind="payment" value={e.payment} /> },
    { key: "employee", header: "الموظف", headerClassName: TH, className: TD, render: (e) => <span className={CELL_SUB}>{e.employee}</span> },
    {
      key: "amount",
      header: "المبلغ",
      headerClassName: TH,
      className: TD,
      align: "end",
      render: (e) => <span className={e.voided ? `${CELL_SUB} num line-through` : CELL_ACCENT}>{fmtMoney(e.amount)}</span>,
    },
    {
      key: "actions",
      header: "إجراءات",
      headerClassName: TH,
      className: TD,
      sortable: false,
      align: "center",
      render: (e) =>
        e.voided ? (
          <span className={`${CELL_SUB} font-semibold`}>ملغي</span>
        ) : (
          <Button className={`${BTN} text-[#B3261E] hover:bg-[#FDECEA] hover:text-[#B3261E]`} onClick={() => onVoid(e)}>
            إلغاء
          </Button>
        ),
    },
  ];
}
