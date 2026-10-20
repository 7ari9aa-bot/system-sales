import { useState } from "react";
import { Clock, Unlock } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import { Image } from "@/cashier/components/ui/image";
import DataTable from "@/cashier/components/ui-kit/DataTable";
import LedgerPage from "@/cashier/components/ui-kit/LedgerPage";
import LedgerStats from "@/cashier/components/ui-kit/LedgerStats";
import PageHero from "@/cashier/components/ui-kit/PageHero";
import ShiftOpenDialog from "@/cashier/components/shifts/ShiftOpenDialog";
import ShiftCloseDialog from "@/cashier/components/shifts/ShiftCloseDialog";
import ShiftDetailsDialog from "@/cashier/components/shifts/ShiftDetailsDialog";
import ShiftFilters from "@/cashier/components/shifts/ShiftFilters";
import shiftColumns from "@/cashier/components/shifts/shiftColumns";
import { BTN, BTN_PRIMARY, LEDGER, LEDGER_FOOTER, LEDGER_TOOLBAR } from "@/cashier/components/ui-kit/ledgerStyles";
import { shiftRow, shiftRows, shiftsSummary } from "@/cashier/lib/storeOpsData";
import { shop } from "@/cashier/lib/mockData";
import { fmtInt, fmtMoney, fmtTime } from "@/cashier/lib/format";


const HERO_IMAGE = "https://media.base44.com/images/public/6ad5982c1b45f350e41ffe73/6e1281bb6_generated_image.png";
const HERO_ALT = "منضدة الكاشير عند إغلاق الوردية مع عدّ النقدية";

export default function ShiftsPage() {
  const [rows, setRows] = useState(shiftRows);
  const [employeeFilter, setEmployeeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [openDialog, setOpenDialog] = useState(false);
  const [closing, setClosing] = useState(null);
  const [details, setDetails] = useState(null);

  const summary = shiftsSummary(rows);
  const filtered = rows.filter((r) => {
    if (employeeFilter && r.employee !== employeeFilter) return false;
    if (statusFilter && r.status !== statusFilter) return false;
    return true;
  });

  function addShift(record) {
    setRows((prev) => [
      shiftRow({
        id: `sh-new-${prev.length + 1}`,
        number: `SH-2026-${String(42 + prev.length).padStart(4, "0")}`,
        date: new Date().toISOString(),
        branch: shop.branch,
        employee: record.employee,
        openingCash: record.openingCash,
        invoices: 0,
        pieces: 0,
        cashSales: 0,
        cardSales: 0,
        walletSales: 0,
        creditSales: 0,
        returnsCash: 0,
        expensesCash: 0,
        variance: 0,
        closedAt: null,
        status: "open",
        note: record.note,
      }),
      ...prev,
    ]);
    toast.success(`تم فتح وردية ${record.employee} برصيد ${fmtMoney(record.openingCash)}`);
  }

  function closeShift(shift, { actual, note }) {
    setRows((prev) =>
      prev.map((r) =>
        r.id === shift.id
          ? shiftRow({
              ...r,
              status: "closed",
              closedAt: new Date().toISOString(),
              variance: +(actual - shift.expected).toFixed(2),
              note: note || r.note,
            })
          : r,
      ),
    );
    toast.success(`تم إغلاق الوردية ${shift.number} — ${actual === shift.expected ? "الخزنة مطابقة" : `فرق ${fmtMoney(actual - shift.expected)}`}`);
  }

  const columns = shiftColumns({ onClose: setClosing, onDetails: setDetails });

  return (
    <LedgerPage
      hero={
        <PageHero image={HERO_IMAGE} imageAlt={HERO_ALT} title="الورديات والخزنة" description="فتح وإغلاق الوردية: رصيد البداية، النقدية المتوقعة والفعلية، وتسجيل الفروق">
          <Button className={BTN} disabled={!summary.open} title={summary.open ? "" : "لا توجد وردية مفتوحة"} onClick={() => setDetails(summary.open)}>
            <Clock />
            الوردية الجارية
          </Button>
          <Button className={BTN_PRIMARY} disabled={Boolean(summary.open)} onClick={() => setOpenDialog(true)}>
            <Unlock />
            فتح وردية جديدة
          </Button>
        </PageHero>
      }
    >
      <ShiftFilters
        employee={employeeFilter}
        onEmployee={(value) => setEmployeeFilter(value === "all" ? "" : value)}
        status={statusFilter}
        onStatus={(value) => setStatusFilter(value === "all" ? "" : value)}
        onReset={() => {
          setEmployeeFilter("");
          setStatusFilter("");
        }}
      />

      <DataTable
        className={LEDGER}
        toolbarClassName={LEDGER_TOOLBAR}
        footerClassName={LEDGER_FOOTER}
        columns={columns}
        rows={filtered}
        pageSize={8}
        emptyTitle="لا توجد ورديات مطابقة"
        emptyDescription="جرّب تغيير الموظف أو حالة الوردية."
        toolbar={
          <div className="num flex items-center gap-3 text-[12px] text-[#7A766C]">
            <Image src={HERO_IMAGE} alt={HERO_ALT} className="h-[34px] w-[34px] overflow-hidden rounded-[4px] border border-[#DED8CD]" />
            <span>
              {fmtInt(filtered.length)} وردية • مبيعات نقدية {fmtMoney(summary.cashSales)} • فروق {fmtMoney(summary.differences)}
            </span>
          </div>
        }
      />

      <LedgerStats
        stats={[
          {
            label: "الوردية المفتوحة",
            value: summary.open ? summary.open.employee : "لا توجد",
            hint: summary.open ? `فتحت ${fmtTime(summary.open.date)} برصيد ${fmtMoney(summary.open.openingCash)}` : "افتح وردية لبدء البيع",
          },
          { label: "النقدية المتوقعة", value: fmtMoney(summary.open?.expected ?? 0), hint: "الخزنة الحالية بعد المبيعات والمصروفات", accent: true },
          { label: "خزنة الورديات المغلقة", value: fmtMoney(summary.collected), hint: `${fmtInt(summary.closedCount)} وردية مغلقة` },
          { label: "إجمالي الفروق", value: fmtMoney(summary.differences), hint: "مجموع الفروق في العدّ" },
        ]}
      />

      <ShiftOpenDialog open={openDialog} onOpenChange={setOpenDialog} onSubmit={addShift} />
      <ShiftCloseDialog open={Boolean(closing)} onOpenChange={(open) => !open && setClosing(null)} shift={closing} onSubmit={(payload) => closeShift(closing, payload)} />
      <ShiftDetailsDialog open={Boolean(details)} onOpenChange={(open) => !open && setDetails(null)} shift={details} />
    </LedgerPage>
  );
}