import { Eye } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import StatusBadge from "@/cashier/components/ui-kit/StatusBadge";
import { BTN, CELL_ACCENT, CELL_EMPTY, CELL_NUM, CELL_SUB, TD, TH } from "@/cashier/components/ui-kit/ledgerStyles";
import { fmtDate, fmtInt, fmtMoney } from "@/cashier/lib/format";

// أعمدة جدول المشتريات: البنود والقطع، تكلفة الفاتورة، وما سُدَّد وما تبقّى للمورد.
export default function purchaseColumns({ onDetails }) {
  return [
    {
      key: "number",
      header: "رقم الفاتورة",
      headerClassName: TH,
      className: TD,
      render: (r) => (
        <span>
          <span className="num block text-[12px] font-semibold text-[#33322E]">{r.number}</span>
          <span className={`mt-0.5 block ${CELL_SUB}`}>{fmtDate(r.date)}</span>
        </span>
      ),
    },
    {
      key: "supplierName",
      header: "المورد",
      headerClassName: TH,
      className: TD,
      render: (r) => (
        <span>
          <span className="block max-w-[200px] truncate text-[12px] font-semibold text-[#33322E]">{r.supplierName}</span>
          <span className={`mt-0.5 block ${CELL_SUB}`}>{r.warehouse}</span>
        </span>
      ),
    },
    {
      key: "items",
      header: "عدد البنود",
      headerClassName: TH,
      className: TD,
      sortable: false,
      align: "center",
      render: (r) => <span className={CELL_NUM}>{fmtInt(r.items.length)}</span>,
    },
    {
      key: "pieces",
      header: "عدد القطع",
      headerClassName: TH,
      className: TD,
      align: "center",
      render: (r) => <span className={`${CELL_NUM} font-semibold`}>{fmtInt(r.pieces)}</span>,
    },
    {
      key: "total",
      header: "إجمالي الفاتورة",
      headerClassName: TH,
      className: TD,
      align: "end",
      render: (r) => <span className={`${CELL_NUM} font-semibold`}>{fmtMoney(r.total)}</span>,
    },
    {
      key: "paid",
      header: "المدفوع",
      headerClassName: TH,
      className: TD,
      align: "end",
      render: (r) => <span className={`${CELL_NUM} text-emerald-600`}>{fmtMoney(r.paid)}</span>,
    },
    {
      key: "balance",
      header: "المستحق",
      headerClassName: TH,
      className: TD,
      align: "end",
      render: (r) => <span className={r.balance > 0 ? CELL_ACCENT : CELL_EMPTY}>{fmtMoney(r.balance)}</span>,
    },
    {
      key: "status",
      header: "الحالة",
      headerClassName: TH,
      className: TD,
      render: (r) => <StatusBadge value={r.status} />,
    },
    {
      key: "actions",
      header: "الإجراءات",
      headerClassName: TH,
      className: TD,
      sortable: false,
      align: "center",
      render: (r) => (
        <Button className={BTN} onClick={() => onDetails(r)}>
          <Eye />
          التفاصيل
        </Button>
      ),
    },
  ];
}