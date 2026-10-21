import { Check, X } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import { CELL_MAIN, CELL_NUM, CELL_SUB, TD, TH } from "@/cashier/components/ui-kit/ledgerStyles";
import { toMinor } from "@/cashier/api/money";
import { RETURN_STATUS_LABEL, SETTLEMENT_LABEL } from "@/cashier/api/purchasingAdapter";
import { fmtDate, fmtInt, fmtMoney } from "@/cashier/lib/format";

const STATUS_TONE = {
  review: "bg-amber-50 text-amber-700 border-amber-200",
  accepted: "bg-emerald-50 text-emerald-700 border-emerald-200",
  rejected: "bg-stone-100 text-stone-500 border-stone-200",
};

function Pill({ tone, children }) {
  return <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold ${tone}`}>{children}</span>;
}

// الأثر على المخزون بيتوقف على حالة المرتجع: خرج من الرف لما اتسجل، ورجع لو المورد رفضه.
function stockEffect(r) {
  if (r.status === "rejected") return <span className={`${CELL_NUM} text-stone-500`}>رجع للرف</span>;
  return <span className={`${CELL_NUM} font-semibold text-rose-600`}>−{fmtInt(r.qty)} خروج</span>;
}

// أعمدة جدول مرتجعات الموردين: الأصناف، أثرها على المخزون، التسوية، وقرار المورد.
export default function supplierReturnColumns({ onAccept, onReject, busyId }) {
  return [
    {
      key: "number",
      header: "رقم المرتجع",
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
          <span className="block max-w-[190px] truncate text-[12px] font-semibold text-[#33322E]">{r.supplierName}</span>
          <span className={`mt-0.5 block ${CELL_SUB}`}>{r.orderId ? `فاتورة ${r.poNumber}` : "بدون فاتورة"}</span>
        </span>
      ),
    },
    {
      key: "items",
      header: "الأصناف",
      headerClassName: TH,
      className: TD,
      sortable: false,
      render: (r) => {
        const first = r.items[0];
        return (
          <span>
            <span className="block max-w-[210px] truncate text-[12px] font-semibold text-[#33322E]">{first?.name ?? "—"}</span>
            <span className={`mt-0.5 block ${CELL_SUB}`}>
              {[first?.color, first?.size].filter(Boolean).join(" / ")}
              {r.items.length > 1 ? ` • و${fmtInt(r.items.length - 1)} صنف آخر` : ""}
            </span>
          </span>
        );
      },
    },
    {
      key: "qty",
      header: "الكمية",
      headerClassName: TH,
      className: TD,
      align: "center",
      render: (r) => <span className={`${CELL_NUM} font-semibold`}>{fmtInt(r.qty)}</span>,
    },
    {
      key: "amount",
      header: "قيمة المرتجع",
      headerClassName: TH,
      className: TD,
      align: "end",
      sortValue: (r) => toMinor(r.amount),
      // Only an ACCEPTED return is money; one still under review is a claim, shown muted.
      render: (r) => (
        <span className={`num font-semibold ${r.status === "accepted" ? "text-[#E8761A]" : "text-[#9A968B]"}`}>{fmtMoney(r.amount)}</span>
      ),
    },
    { key: "stockEffect", header: "أثر المخزون", headerClassName: TH, className: TD, sortable: false, align: "center", render: stockEffect },
    {
      key: "settlement",
      header: "التسوية",
      headerClassName: TH,
      className: TD,
      render: (r) => <span className={CELL_MAIN}>{SETTLEMENT_LABEL[r.settlement] ?? r.settlement}</span>,
    },
    {
      key: "status",
      header: "قرار المورد",
      headerClassName: TH,
      className: TD,
      align: "center",
      render: (r) =>
        r.status === "review" ? (
          <span className="inline-flex items-center gap-1.5">
            <Button className="h-7 px-2 text-[11px]" disabled={busyId === r.id} onClick={() => onAccept(r)}>
              <Check />
              قبول
            </Button>
            <Button variant="outline" className="h-7 px-2 text-[11px]" disabled={busyId === r.id} onClick={() => onReject(r)}>
              <X />
              رفض
            </Button>
          </span>
        ) : (
          <Pill tone={STATUS_TONE[r.status]}>{RETURN_STATUS_LABEL[r.status]}</Pill>
        ),
    },
  ];
}
