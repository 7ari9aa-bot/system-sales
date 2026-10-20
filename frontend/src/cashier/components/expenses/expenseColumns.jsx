import { Button } from "@/cashier/components/ui/button";
import StatusBadge from "@/cashier/components/ui-kit/StatusBadge";
import { BTN, CELL_ACCENT, CELL_MAIN, CELL_SUB, TD, TH } from "@/cashier/components/ui-kit/ledgerStyles";
import { fmtDateTime, fmtMoney } from "@/cashier/lib/format";

// أعمدة جدول المصروفات: الرقم والتاريخ، التصنيف، البيان، طريقة الدفع، الموظف، والمبلغ.
export default function expenseColumns({ onEdit, onDelete }) {
  return [
    {
      key: "number",
      header: "رقم المصروف",
      headerClassName: TH,
      className: TD,
      render: (e) => (
        <span>
          <span className="block num text-[12px] font-semibold text-[#33322E]">{e.number}</span>
          <span className={`mt-0.5 block num ${CELL_SUB}`}>{fmtDateTime(e.date)}</span>
        </span>
      ),
    },
    { key: "category", header: "التصنيف", headerClassName: TH, className: TD, render: (e) => <span className={CELL_MAIN}>{e.category}</span> },
    { key: "description", header: "البيان", headerClassName: TH, className: TD, render: (e) => <span className={CELL_MAIN}>{e.description}</span> },
    { key: "payment", header: "طريقة الدفع", headerClassName: TH, className: TD, render: (e) => <StatusBadge kind="payment" value={e.payment} /> },
    { key: "employee", header: "الموظف", headerClassName: TH, className: TD, render: (e) => <span className={CELL_SUB}>{e.employee}</span> },
    { key: "amount", header: "المبلغ", headerClassName: TH, className: TD, align: "end", render: (e) => <span className={CELL_ACCENT}>{fmtMoney(e.amount)}</span> },
    {
      key: "actions",
      header: "إجراءات",
      headerClassName: TH,
      className: TD,
      sortable: false,
      align: "center",
      render: (e) => (
        <span className="flex items-center justify-center gap-1.5">
          <Button className={BTN} onClick={() => onEdit(e)}>
            تعديل
          </Button>
          <Button className={`${BTN} text-[#B3261E] hover:bg-[#FDECEA] hover:text-[#B3261E]`} onClick={() => onDelete(e)}>
            حذف
          </Button>
        </span>
      ),
    },
  ];
}