import StatusBadge from "@/cashier/components/ui-kit/StatusBadge";
import { CELL_MAIN, CELL_NUM, CELL_SUB, TD, TH } from "@/cashier/components/ui-kit/ledgerStyles";
import { fmtDate, fmtInt, fmtMoney } from "@/cashier/lib/format";

// أعمدة جدول مرتجعات الموردين: الصنف والكمية، أثرها على المخزون، وتسوية الحساب.
export default function supplierReturnColumns() {
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
          <span className="block max-w-[180px] truncate text-[12px] font-semibold text-[#33322E]">{r.supplierName}</span>
          <span className={`num mt-0.5 block ${CELL_SUB}`}>{r.poNumber}</span>
        </span>
      ),
    },
    {
      key: "productName",
      header: "الصنف",
      headerClassName: TH,
      className: TD,
      render: (r) => (
        <span>
          <span className="block max-w-[210px] truncate text-[12px] font-semibold text-[#33322E]">{r.productName}</span>
          <span className={`mt-0.5 block ${CELL_SUB}`}>
            {r.color} / {r.size}
          </span>
        </span>
      ),
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
      key: "unitCost",
      header: "تكلفة القطعة",
      headerClassName: TH,
      className: TD,
      align: "end",
      render: (r) => <span className={`${CELL_NUM} text-[#7A766C]`}>{fmtMoney(r.unitCost)}</span>,
    },
    {
      key: "amount",
      header: "قيمة المرتجع",
      headerClassName: TH,
      className: TD,
      align: "end",
      render: (r) => <span className="num font-semibold text-[#E8761A]">{fmtMoney(r.amount)}</span>,
    },
    {
      key: "stockEffect",
      header: "أثر المخزون",
      headerClassName: TH,
      className: TD,
      sortable: false,
      align: "center",
      render: (r) => <span className={`${CELL_NUM} font-semibold text-rose-600`}>−{fmtInt(r.qty)} خروج</span>,
    },
    {
      key: "reason",
      header: "السبب",
      headerClassName: TH,
      className: TD,
      render: (r) => <span className={CELL_MAIN}>{r.reason}</span>,
    },
    {
      key: "settlement",
      header: "تسوية الحساب",
      headerClassName: TH,
      className: TD,
      render: (r) => <StatusBadge kind="supplier_return" value={r.settlement} />,
    },
    {
      key: "status",
      header: "الحالة",
      headerClassName: TH,
      className: TD,
      render: (r) => <StatusBadge kind="return" value={r.status} />,
    },
  ];
}