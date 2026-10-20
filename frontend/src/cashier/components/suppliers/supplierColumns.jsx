import StatusBadge from "@/cashier/components/ui-kit/StatusBadge";
import SupplierHistoryButton from "@/cashier/components/suppliers/SupplierHistoryButton";
import { CELL_ACCENT, CELL_EMPTY, CELL_MAIN, CELL_NUM, CELL_SUB, TD, TH } from "@/cashier/components/ui-kit/ledgerStyles";
import { supplierReturnCredit } from "@/cashier/lib/storeOpsData";
import { fmtDate, fmtInt, fmtMoney } from "@/cashier/lib/format";

// أعمدة جدول الموردين: التوريدات، آخر تعامل، والرصيد المستحق بعد خصم المرتجعات.
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
      sortValue: (s) => +(s.balance - supplierReturnCredit(s.id)).toFixed(2),
      render: (s) => {
        const credit = supplierReturnCredit(s.id);
        const net = +(s.balance - credit).toFixed(2);
        return (
          <span>
            <span className={`block ${net > 0 ? CELL_ACCENT : CELL_EMPTY}`}>{fmtMoney(net)}</span>
            {credit > 0 && <span className={`mt-0.5 block ${CELL_SUB}`}>مرتجعات مخصومة {fmtMoney(credit)}</span>}
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