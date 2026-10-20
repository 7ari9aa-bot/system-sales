import StatusBadge from "@/cashier/components/ui-kit/StatusBadge";
import SupplierHistoryButton from "@/cashier/components/suppliers/SupplierHistoryButton";
import { CELL_ACCENT, CELL_EMPTY, CELL_MAIN, CELL_NUM, CELL_SUB, TD, TH } from "@/cashier/components/ui-kit/ledgerStyles";
import { toMinor } from "@/cashier/api/money";
import { fmtDate, fmtInt, fmtMoney } from "@/cashier/lib/format";

// أعمدة جدول الموردين. الرصيد جاي من الخادم محسوب من المستندات وبعد خصم المرتجعات المقبولة، فبيتعرض زي ما هو.
// (خصم المرتجعات هنا مرة تانية كان هيخصمها مرتين.)
export default function supplierColumns({ onHistory }) {
  return [
    {
      key: "name",
      header: "المورد",
      headerClassName: TH,
      className: TD,
      render: (s) => (
        <span>
          <span className="block text-[12px] font-semibold text-[#33322E]">{s.name}</span>
          <span className={`mt-0.5 block ${CELL_SUB}`}>{s.company}</span>
        </span>
      ),
    },
    { key: "agent", header: "المسؤول", headerClassName: TH, className: TD, render: (s) => <span className={CELL_MAIN}>{s.agent}</span> },
    {
      key: "phone",
      header: "الهاتف",
      headerClassName: TH,
      className: TD,
      render: (s) => <span className={CELL_NUM}>{s.phone}</span>,
    },
    {
      key: "city",
      header: "المدينة",
      headerClassName: TH,
      className: TD,
      render: (s) => <span className={CELL_SUB}>{s.city}</span>,
    },
    {
      key: "items",
      header: "عدد الأصناف",
      headerClassName: TH,
      className: TD,
      align: "center",
      render: (s) => <span className={`${CELL_NUM} font-semibold`}>{fmtInt(s.items)}</span>,
    },
    {
      key: "lastDeal",
      header: "آخر توريد",
      headerClassName: TH,
      className: TD,
      render: (s) => <span className={`${CELL_NUM} text-[#7A766C]`}>{fmtDate(s.lastDeal)}</span>,
    },
    {
      key: "total",
      header: "إجمالي التوريد",
      headerClassName: TH,
      className: TD,
      align: "end",
      render: (s) => <span className={CELL_NUM}>{fmtMoney(s.total)}</span>,
    },
    {
      key: "balance",
      header: "المستحق للمورد",
      headerClassName: TH,
      className: TD,
      align: "end",
      sortValue: (s) => toMinor(s.balance),
      render: (s) => {
        const owed = toMinor(s.balance);
        return (
          <span>
            <span className={`block ${owed > 0 ? CELL_ACCENT : CELL_EMPTY}`}>{fmtMoney(s.balance)}</span>
            {owed < 0 && <span className={`mt-0.5 block ${CELL_SUB}`}>رصيد لصالح المحل</span>}
            {toMinor(s.credit) > 0 && <span className={`mt-0.5 block ${CELL_SUB}`}>مرتجعات مخصومة {fmtMoney(s.credit)}</span>}
          </span>
        );
      },
    },
    {
      key: "status",
      header: "الحالة",
      headerClassName: TH,
      className: TD,
      render: (s) => <StatusBadge kind="supplier" value={s.status} />,
    },
    {
      key: "history",
      header: "سجل التوريدات",
      headerClassName: TH,
      className: TD,
      sortable: false,
      align: "center",
      render: (s) => <SupplierHistoryButton onClick={() => onHistory(s)} />,
    },
  ];
}