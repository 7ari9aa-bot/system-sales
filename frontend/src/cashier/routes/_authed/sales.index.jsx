import { Link, useNavigate } from "react-router-dom";
import { Download, FilePlus2 } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import SalesLogFilters from "@/cashier/components/sales/SalesLogFilters";
import SalesLogTable from "@/cashier/components/sales/SalesLogTable";
import LogBadge from "@/cashier/components/sales/LogBadge";
import InvoiceRowActions from "@/cashier/components/sales/InvoiceRowActions";
import OperationsLogDialog from "@/cashier/components/sales/OperationsLogDialog";
import ReceiptDialog from "@/cashier/components/pos/ReceiptDialog";
import { useAuth } from "@/lib/AuthContext";
import { useShifts } from "@/cashier/api/useShifts";
import { useShiftSales } from "@/cashier/api/usePosSale";
import { filterRows, totalsOf } from "@/cashier/api/salesLog";
import { fmtDateTime, fmtInt, fmtMoney, INVOICE_STATUS, PAYMENT_METHODS } from "@/cashier/lib/format";
import { exportCsv } from "@/cashier/lib/exportCsv";


// الفلاتر الافتراضية: آخر أسبوع. «مسح الفلاتر» يرجع لهذه القيم.
const DEFAULT_FILTERS = { from: "", to: "", term: "", payment: "", status: "" };

const BTN =
  "h-10 gap-2 rounded-[10px] border border-[#e3d6c2] bg-white px-[18px] text-[13px] font-bold text-[#0F172A] shadow-none transition-[background-color,box-shadow,border-color] duration-150 hover:border-[#F97316] hover:bg-[#FFF4E8] hover:text-[#0F172A] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#F97316] focus-visible:ring-0 active:shadow-[inset_0_2px_4px_rgba(15,23,42,.15)]";
const BTN_PRIMARY =
  "h-10 gap-2 rounded-[10px] border border-[#F97316] bg-[#F97316] px-[18px] text-[13px] font-bold text-white shadow-none transition-[background-color,box-shadow,border-color] duration-150 hover:border-[#F97316] hover:bg-[#ea6a0a] hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#F97316] focus-visible:ring-0 active:shadow-[inset_0_2px_4px_rgba(15,23,42,.15)]";

export default function SalesLogPage() {
  const navigate = useNavigate();
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [logInvoice, setLogInvoice] = useState(null);
  const [receipt, setReceipt] = useState(null);

  const { user } = useAuth();
  const shiftsQuery = useShifts({ employees: user?.id ? { [user.id]: user.full_name || user.email } : {} });
  const shifts = shiftsQuery.data ?? [];
  const [pickedShift, setPickedShift] = useState("");
  const shiftId = pickedShift || shifts[0]?.id || "";
  const salesQuery = useShiftSales(shiftId, { cashier: shifts.find((x) => x.id === shiftId)?.employeeId === user?.id ? (user.full_name || user.email || "") : "" });

  const rows = useMemo(() => filterRows(salesQuery.data ?? [], filters), [salesQuery.data, filters]);
  const activeCount = ["from", "to", "term", "payment", "status"].filter((k) => filters[k] !== "").length;
  const totals = totalsOf(rows);

  const openInvoice = (inv) => navigate(`/cashier/sales/${inv.id}?shift=${encodeURIComponent(shiftId)}`);
  const shift = shifts.find((x) => x.id === shiftId);

  const columns = [
    {
      key: "number",
      header: "رقم الفاتورة",
      render: (inv) => <span className="num font-bold text-[#d9600a]">{inv.number}</span>,
    },
    {
      key: "date",
      header: "التاريخ والوقت",
      render: (inv) => <span className="num text-[12px] text-[#7a6f61]">{fmtDateTime(inv.date)}</span>,
    },
    {
      key: "pieces",
      header: <span title="عدد القطع = مجموع وحدات كل الأصناف داخل الفاتورة">عدد القطع</span>,
      align: "center",
      render: (inv) => <span className="num">{fmtInt(inv.pieces)}</span>,
    },
    {
      key: "total",
      header: "إجمالي الفاتورة",
      render: (inv) => <span className="num font-bold">{fmtMoney(inv.total)}</span>,
    },
    {
      key: "payment",
      header: "طريقة الدفع",
      render: (inv) => (
        <LogBadge label={inv.payment === "mixed" ? inv.paymentLabel : (PAYMENT_METHODS[inv.payment]?.label ?? inv.payment)} tone={PAYMENT_METHODS[inv.payment]?.tone} />
      ),
    },
    {
      key: "status",
      header: "حالة الفاتورة",
      render: (inv) => (
        <LogBadge label={INVOICE_STATUS[inv.status]?.label ?? inv.status} tone={INVOICE_STATUS[inv.status]?.tone} />
      ),
    },
    {
      key: "actions",
      header: "الإجراءات",
      sortable: false,
      align: "center",
      render: (inv) => (
        // منع فتح صفحة التفاصيل عند استخدام قائمة الإجراءات.
        <div onClick={(event) => event.stopPropagation()}>
          <InvoiceRowActions
            invoice={inv}
            onView={() => openInvoice(inv)}
            onPrint={() => {
              setReceipt(inv.receipt);
            }}
            onReturn={() => navigate(`/cashier/returns?invoice=${encodeURIComponent(inv.number)}`)}
            onLog={() => setLogInvoice(inv)}
          />
        </div>
      ),
    },
  ];

  return (
    <div className="-mx-2 -my-2 min-h-[calc(100vh-1rem)] bg-[#FAF7F2] px-4 pb-12 pt-6 text-[#0F172A] sm:-mx-3 sm:px-8 lg:px-10 lg:pt-9">
      <div className="mb-[22px] flex flex-wrap items-end justify-between gap-6">
        <div>
          <h1 className="text-[26px] font-extrabold leading-[1.2] tracking-[-.03em] sm:text-[32px]">سجل المبيعات</h1>
          <p className="mt-1.5 text-[13px] text-[#6b6358]">
            فواتير الوردية المختارة مع البحث والفلاتر. اضغط أي صف لعرض التفاصيل
          </p>
        </div>
        <div className="flex flex-wrap gap-2.5">
          {[
            { label: "عدد الفواتير", value: `${fmtInt(rows.length)} فاتورة` },
            { label: "إجمالي المبيعات (بعد الخصم)", value: fmtMoney(totals.total) },
            { label: "عدد القطع المباعة", value: fmtInt(totals.pieces) },
          ].map((chip) => (
            <div
              key={chip.label}
              className="min-w-[170px] rounded-xl border border-[#eadfce] bg-white px-4 py-2.5 shadow-[0_1px_2px_rgba(15,23,42,.04)]"
            >
              <small className="block text-[11px] font-semibold text-[#7a6f61]">{chip.label}</small>
              <b className="num mt-1 block text-[20px] font-bold leading-tight">{chip.value}</b>
            </div>
          ))}
        </div>
      </div>

      <div className="mb-[18px] flex flex-wrap gap-2.5">
        <Button asChild className={BTN_PRIMARY}>
          <Link to="/cashier/pos">
            <FilePlus2 className="h-4 w-4" />
            فاتورة بيع جديدة
          </Link>
        </Button>
        <Button
          className={BTN}
          onClick={() => {
            exportCsv(
              `سجل-المبيعات-${shift?.number ?? "وردية"}.csv`,
              [
                { header: "رقم الفاتورة", key: "number" },
                { header: "التاريخ", key: "date" },
                { header: "عدد القطع", key: "pieces" },
                { header: "الإجمالي", key: "total" },
                { header: "طريقة الدفع", value: (inv) => inv.paymentLabel },
                { header: "الحالة", value: (inv) => INVOICE_STATUS[inv.status]?.label ?? inv.status },
              ],
              rows,
            );
            toast.success(`تم تصدير ${rows.length} فاتورة`);
          }}
        >
          <Download className="h-4 w-4" />
          تصدير Excel
        </Button>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2 text-[13px]">
        <label htmlFor="sales-shift" className="font-semibold text-[#6b6358]">الوردية</label>
        <select
          id="sales-shift"
          value={shiftId}
          onChange={(e) => setPickedShift(e.target.value)}
          className="h-9 rounded-lg border border-[#e3d6c2] bg-white px-3 text-[13px]"
        >
          {shifts.map((x) => (
            <option key={x.id} value={x.id}>
              {x.number} • {fmtDateTime(x.date)} • {x.status === "open" ? "مفتوحة" : "مغلقة"}
            </option>
          ))}
        </select>
        {salesQuery.isError ? <span role="alert" className="font-semibold text-rose-600">تعذّر تحميل فواتير هذه الوردية</span> : null}
        {salesQuery.isLoading || shiftsQuery.isLoading ? <span role="status" className="text-[#7a6f61]">جارٍ التحميل…</span> : null}
      </div>

      <SalesLogFilters
        filters={filters}
        onChange={setFilters}
        onReset={() => setFilters(DEFAULT_FILTERS)}
        activeCount={activeCount}
      />

      <SalesLogTable
        columns={columns}
        rows={rows}
        pageSize={10}
        onRowClick={openInvoice}
        emptyTitle="لا توجد فواتير مطابقة للفلاتر"
        emptyDescription="عدّل الفترة أو امسح الفلاتر لعرض كل الفواتير."
        emptyAction={
          <Button variant="outline" size="sm" onClick={() => setFilters(DEFAULT_FILTERS)}>
            مسح الفلاتر
          </Button>
        }
      />

      <OperationsLogDialog open={!!logInvoice} onOpenChange={(o) => !o && setLogInvoice(null)} invoice={logInvoice} />
      <ReceiptDialog open={!!receipt} onOpenChange={(o) => !o && setReceipt(null)} receipt={receipt} />
    </div>
  );
}