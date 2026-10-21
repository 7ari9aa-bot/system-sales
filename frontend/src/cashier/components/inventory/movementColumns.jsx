import StatusBadge from "@/cashier/components/ui-kit/StatusBadge";
import ColorSwatch from "@/cashier/components/ui-kit/ColorSwatch";
import { CELL_MAIN, CELL_SUB, TD, TH } from "@/cashier/components/ui-kit/ledgerStyles";
import { colorHex } from "@/cashier/lib/uiConstants";
import { fmtDateTime, fmtInt } from "@/cashier/lib/format";

// أعمدة حركة الأصناف: التاريخ، المنتج بلونه ومقاسه ورمزه، نوع الحركة، داخل/خارج، الرصيد، والمستند، والموظف.
export default function movementColumns() {
  return [
    {
      key: "date",
      header: "التاريخ",
      headerClassName: TH,
      className: TD,
      render: (m) => <span className={`num ${CELL_SUB}`}>{fmtDateTime(m.date)}</span>,
    },
    {
      key: "productName",
      header: "المنتج",
      headerClassName: TH,
      className: TD,
      render: (m) => (
        <span className="block max-w-[230px]">
          <span className={`block truncate ${CELL_MAIN} font-medium`}>{m.productName}</span>
          <span className="mt-0.5 flex items-center gap-2 text-[11px] text-[#7A766C]">
            {m.color ? <ColorSwatch color={m.color} hex={colorHex(m.color)} showLabel={false} /> : null}
            {m.size ? <span>مقاس {m.size}</span> : null}
            <span className="num">{m.sku}</span>
          </span>
        </span>
      ),
    },
    { key: "type", header: "نوع الحركة", headerClassName: TH, className: TD, render: (m) => <StatusBadge kind="movement" value={m.reason} /> },
    {
      key: "qtyIn",
      header: "داخل",
      headerClassName: TH,
      className: TD,
      align: "center",
      render: (m) => <span className="num font-semibold text-emerald-600">{m.qtyIn ? `+${fmtInt(m.qtyIn)}` : "—"}</span>,
    },
    {
      key: "qtyOut",
      header: "خارج",
      headerClassName: TH,
      className: TD,
      align: "center",
      render: (m) => <span className="num font-semibold text-rose-600">{m.qtyOut ? `-${fmtInt(m.qtyOut)}` : "—"}</span>,
    },
    {
      key: "balance",
      header: "الرصيد بعد الحركة",
      headerClassName: TH,
      className: TD,
      align: "center",
      render: (m) => <span className="num font-bold text-[#33322E]">{m.balance === null ? "—" : fmtInt(m.balance)}</span>,
    },
    { key: "doc", header: "المستند", headerClassName: TH, className: TD, render: (m) => <span className="num text-[11px] text-[#7A766C]">{m.doc}</span> },
    // Blank (a dash) when nobody was recorded: older rows and system actions, never a guess.
    { key: "staff", header: "الموظف", headerClassName: TH, className: TD, render: (m) => <span className={CELL_SUB}>{m.staff ?? "—"}</span> },
  ];
}