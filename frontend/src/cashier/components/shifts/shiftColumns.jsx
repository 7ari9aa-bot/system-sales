import { Eye, FileText, LockKeyhole } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import StatusBadge from "@/cashier/components/ui-kit/StatusBadge";
import { BTN, BTN_PRIMARY, CELL_ACCENT, CELL_EMPTY, CELL_MAIN, CELL_NUM, CELL_SUB, TD, TH } from "@/cashier/components/ui-kit/ledgerStyles";
import { fmtDate, fmtMoney, fmtTime } from "@/cashier/lib/format";
import { cn } from "@/cashier/lib/utils";

// لون الفرق: مطابق، زيادة، أو عجز.
function differenceTone(value) {
  if (value === 0) return "text-emerald-600";
  return value > 0 ? "text-sky-600" : "text-rose-600";
}

// أعمدة جدول الورديات: الفتح والإغلاق، الأرصدة، المتوقع والفعلي والفرق.
export default function shiftColumns({ onClose, onDetails, onReport }) {
  return [
    {
      key: "number",
      header: "الوردية",
      headerClassName: TH,
      className: TD,
      render: (r) => (
        <span>
          <span className="block num text-[12px] font-semibold text-[#33322E]">{r.number}</span>
          <span className={`mt-0.5 block ${CELL_SUB}`}>{r.employee}</span>
        </span>
      ),
    },
    {
      key: "date",
      header: "الفتح والإغلاق",
      headerClassName: TH,
      className: TD,
      render: (r) => (
        <span className="block">
          <span className={`block ${CELL_MAIN}`}>
            {fmtDate(r.date)} • {fmtTime(r.date)}
          </span>
          <span className={`mt-0.5 block ${CELL_SUB}`}>{r.closedAt ? `إغلاق ${fmtTime(r.closedAt)}` : "لم تُغلق بعد"}</span>
        </span>
      ),
    },
    { key: "status", header: "الحالة", headerClassName: TH, className: TD, render: (r) => <StatusBadge kind="shift" value={r.status} /> },
    { key: "openingCash", header: "رصيد البداية", headerClassName: TH, className: TD, align: "end", render: (r) => <span className={CELL_NUM}>{fmtMoney(r.openingCash)}</span> },
    { key: "salesTotal", header: "إجمالي الفواتير", headerClassName: TH, className: TD, align: "end", render: (r) => <span className={CELL_NUM}>{fmtMoney(r.salesTotal)}</span> },
    {
      key: "returnsTotal",
      header: "المرتجعات",
      headerClassName: TH,
      className: TD,
      align: "end",
      render: (r) => <span className={`${CELL_NUM} text-rose-600`}>−{fmtMoney(r.returnsTotal)}</span>,
    },
    { key: "closingBalance", header: "رصيد نهاية اليوم", headerClassName: TH, className: TD, align: "end", render: (r) => <span className={CELL_ACCENT}>{fmtMoney(r.closingBalance)}</span> },
    {
      key: "actions",
      header: "إجراءات",
      headerClassName: TH,
      className: TD,
      sortable: false,
      align: "center",
      render: (r) => (
        <span className="flex items-center justify-center gap-1.5">
          <Button className={BTN} onClick={() => onReport(r)}>
            <FileText />
            تقرير اليوم
          </Button>
          {r.status === "open" ? (
            <Button className={BTN_PRIMARY} onClick={() => onClose(r)}>
              <LockKeyhole />
              إغلاق الوردية
            </Button>
          ) : (
            <Button className={BTN} onClick={() => onDetails(r)}>
              <Eye />
              التفاصيل
            </Button>
          )}
        </span>
      ),
    },
  ];
}