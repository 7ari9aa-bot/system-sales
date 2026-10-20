import { Eye } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import { BTN, CELL_ACCENT, CELL_EMPTY, CELL_NUM, CELL_SUB, TD, TH } from "@/cashier/components/ui-kit/ledgerStyles";
import { toMinor } from "@/cashier/api/money";
import { PAYMENT_LABEL, RECEIPT_LABEL } from "@/cashier/api/purchasingAdapter";
import { fmtDate, fmtInt, fmtMoney } from "@/cashier/lib/format";

const RECEIPT_TONE = {
  received: "bg-emerald-50 text-emerald-700 border-emerald-200",
  draft: "bg-amber-50 text-amber-700 border-amber-200",
  cancelled: "bg-stone-100 text-stone-500 border-stone-200",
};
const PAYMENT_TONE = {
  paid: "bg-emerald-50 text-emerald-700 border-emerald-200",
  partial: "bg-sky-50 text-sky-700 border-sky-200",
  unpaid: "bg-amber-50 text-amber-700 border-amber-200",
};

function Pill({ tone, children }) {
  return <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold ${tone}`}>{children}</span>;
}

// أعمدة جدول المشتريات. الاستلام والدفع حالتين منفصلتين: ممكن تستلم البضاعة النهارده وتدفع بعد شهر.
export default function purchaseColumns({ onDetails }) {
  return [
    {
      key: "number",
      header: "رقم الفاتورة",
      headerClassName: TH,
      className: TD,
      render: (r) => (
        <span>
          <span className={`num block text-[12px] font-semibold ${r.receipt === "cancelled" ? "text-[#9A968B] line-through" : "text-[#33322E]"}`}>{r.number}</span>
          <span className={`mt-0.5 block ${CELL_SUB}`}>{fmtDate(r.date)}</span>
        </span>
      ),
    },
    {
      key: "supplierName",
      header: "المورد",
      headerClassName: TH,
      className: TD,
      render: (r) => <span className="block max-w-[200px] truncate text-[12px] font-semibold text-[#33322E]">{r.supplierName}</span>,
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
      sortValue: (r) => toMinor(r.total),
      render: (r) => <span className={`${CELL_NUM} font-semibold`}>{fmtMoney(r.total)}</span>,
    },
    {
      key: "paid",
      header: "المدفوع",
      headerClassName: TH,
      className: TD,
      align: "end",
      sortValue: (r) => toMinor(r.paid),
      render: (r) => <span className={`${CELL_NUM} text-emerald-600`}>{fmtMoney(r.paid)}</span>,
    },
    {
      key: "balance",
      header: "المستحق",
      headerClassName: TH,
      className: TD,
      align: "end",
      sortValue: (r) => toMinor(r.balance),
      render: (r) => <span className={toMinor(r.balance) > 0 ? CELL_ACCENT : CELL_EMPTY}>{fmtMoney(r.balance)}</span>,
    },
    {
      key: "receipt",
      header: "الاستلام",
      headerClassName: TH,
      className: TD,
      align: "center",
      render: (r) => <Pill tone={RECEIPT_TONE[r.receipt]}>{RECEIPT_LABEL[r.receipt]}</Pill>,
    },
    {
      key: "payment",
      header: "الدفع",
      headerClassName: TH,
      className: TD,
      align: "center",
      // A draft or cancelled invoice has nothing to pay yet.
      render: (r) => (r.receipt === "received" ? <Pill tone={PAYMENT_TONE[r.payment]}>{PAYMENT_LABEL[r.payment]}</Pill> : <span className={CELL_EMPTY}>—</span>),
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
