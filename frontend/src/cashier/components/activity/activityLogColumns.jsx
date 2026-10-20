import StatusBadge from "@/cashier/components/ui-kit/StatusBadge";
import { CELL_SUB, TD, TH } from "@/cashier/components/ui-kit/ledgerStyles";
import { fmtDateTime } from "@/cashier/lib/format";

// أعمدة سجل العمليات: العملية ومستندها، التفاصيل، الموظف، الفرع، والتاريخ.
export default function activityLogColumns() {
  return [
    {
      key: "type",
      header: "العملية",
      headerClassName: TH,
      className: TD,
      render: (r) => (
        <span className="flex items-center gap-2">
          <StatusBadge kind="activity" value={r.type} />
          <span className="num text-[11px] text-[#7A766C]">{r.doc}</span>
        </span>
      ),
    },
    {
      key: "details",
      header: "التفاصيل",
      headerClassName: TH,
      className: TD,
      render: (r) => <span className="block max-w-[420px] text-xs text-[#33322E]">{r.details}</span>,
    },
    { key: "employee", header: "الموظف", headerClassName: TH, className: TD, render: (r) => <span className="text-xs text-[#33322E]">{r.employee}</span> },
    { key: "branch", header: "الفرع / المخزن", headerClassName: TH, className: TD, render: (r) => <span className={CELL_SUB}>{r.branch}</span> },
    { key: "date", header: "التاريخ والوقت", headerClassName: TH, className: TD, render: (r) => <span className="num text-xs text-[#33322E]">{fmtDateTime(r.date)}</span> },
  ];
}