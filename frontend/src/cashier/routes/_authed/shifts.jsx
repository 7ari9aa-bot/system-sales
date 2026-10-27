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
import DayReport from "@/cashier/components/shifts/DayReport";
import ShiftFilters from "@/cashier/components/shifts/ShiftFilters";
import shiftColumns from "@/cashier/components/shifts/shiftColumns";
import { BTN, BTN_PRIMARY, LEDGER, LEDGER_FOOTER, LEDGER_TOOLBAR } from "@/cashier/components/ui-kit/ledgerStyles";
import { canStartAnotherDay } from "@/cashier/api/shiftState";
import { closeSummary, coverageNote, employeeMap, shiftEmployees, shiftsSummary } from "@/cashier/api/shiftAdapter";
import { useClosePreview, useCloseShift, useHeldCount, useOpenChoice, useOpenShift, useShifts } from "@/cashier/api/useShifts";
import { useAuth } from "@/lib/AuthContext";
import { useTenantUsers } from "@/cashier/api/useTenantUsers";
import { fmtInt, fmtMoney, fmtMoneyOrDash, fmtTime } from "@/cashier/lib/format";


const HERO_IMAGE = "https://media.base44.com/images/public/6ad5982c1b45f350e41ffe73/6e1281bb6_generated_image.png";
const HERO_ALT = "منضدة الكاشير عند إغلاق الوردية مع عدّ النقدية";

function messageOf(err) {
  if (!err) return null;
  if (err.status === 403) return "ليست لديك صلاحية لهذه العملية.";
  if (err.status === 409) return "الوردية تغيّرت حالتها. حدّث الصفحة وحاول مرة أخرى.";
  return err.message || "حدث خطأ غير متوقع. حاول مرة أخرى.";
}

export default function ShiftsPage() {
  const { user } = useAuth?.() ?? {};
  const startChoice = useOpenChoice(true); // which registers are free right now: gates the Start Day button
  const members = useTenantUsers(); // names for the days other people started; may be hidden from a cashier
  const { data: rows = [], isLoading, error: loadError, refetch } = useShifts({ employees: employeeMap(members.data, user?.id ? { id: user.id, name: user.full_name || user.email } : null) });
  const openShift = useOpenShift();
  const closeShift = useCloseShift();
  const [employeeFilter, setEmployeeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [openDialog, setOpenDialog] = useState(false);
  const [closing, setClosing] = useState(null);
  const [details, setDetails] = useState(null);
  const [report, setReport] = useState(null);
  const preview = useClosePreview(closing?.id, Boolean(closing));
  const heldCount = useHeldCount(closing?.id, Boolean(closing));

  const summary = shiftsSummary(rows);
  const filtered = rows.filter((r) => {
    if (employeeFilter && r.employeeId !== employeeFilter) return false;
    if (statusFilter && r.status !== statusFilter) return false;
    return true;
  });

  function submitOpen({ openingCash, registerId }) {
    openShift.mutate(
      { openingCash, registerId },
      {
        onSuccess: () => {
          setOpenDialog(false);
          toast.success(`بدأ اليوم برصيد ${fmtMoney(Number(openingCash))}`);
        },
      },
    );
  }

  function submitClose() {
    const shift = closing;
    closeShift.mutate(
      { sessionId: shift.id },
      {
        onSuccess: (closed) => {
          setClosing(null);
          const sum = closeSummary(closed, shift);
          toast.success(`تم إغلاق اليوم ${shift.number}${sum.closingBalance == null ? "" : ` — رصيد النهاية ${fmtMoney(sum.closingBalance)}`}`);
          // The day's report opens right after closing: sales, returns, exchanges and the closing balance.
          setReport({ ...shift, status: "closed", closedAt: sum.closedAt ?? new Date().toISOString(), closingBalance: sum.closingBalance });
        },
      },
    );
  }

  const columns = shiftColumns({ onClose: setClosing, onDetails: setDetails, onReport: setReport });

  return (
    <LedgerPage
      hero={
        <PageHero image={HERO_IMAGE} imageAlt={HERO_ALT} title="سجل يوم العمل" description="بداية اليوم: الرصيد اللي سجّله الكاشير. نهاية اليوم: محسوبة من رصيد البداية والفواتير والمرتجعات، وليست عدًّا فعليًا للنقدية.">
          <Button className={BTN} disabled={!summary.open} title={summary.open ? "" : "لم يبدأ اليوم بعد"} onClick={() => setDetails(summary.open)}>
            <Clock />
            اليوم الجاري
          </Button>
          <Button className={BTN_PRIMARY} disabled={!canStartAnotherDay(startChoice.data)} title={canStartAnotherDay(startChoice.data) ? "" : "كل أجهزة الكاشير بدأ عليها يوم مفتوح"} onClick={() => setOpenDialog(true)}>
            <Unlock />
            ابدأ اليوم
          </Button>
        </PageHero>
      }
    >
      {loadError ? (
        <div role="alert" className="mb-3 flex items-center justify-between rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
          <span>تعذّر تحميل الورديات: {messageOf(loadError)}</span>
          <Button variant="outline" onClick={() => refetch()}>إعادة المحاولة</Button>
        </div>
      ) : null}

      <ShiftFilters
        employees={shiftEmployees(rows)}
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
        emptyTitle={isLoading ? "جارٍ التحميل…" : "لا توجد ورديات مطابقة"}
        emptyDescription="جرّب تغيير الموظف أو حالة الوردية."
        toolbar={
          <div className="num flex items-center gap-3 text-[12px] text-[#7A766C]">
            <Image src={HERO_IMAGE} alt={HERO_ALT} className="h-[34px] w-[34px] overflow-hidden rounded-[4px] border border-[#DED8CD]" />
            <span>
              {fmtInt(filtered.length)} يوم • المبيعات {fmtMoney(summary.salesTotal)} • المرتجعات {fmtMoney(summary.returnsTotal)}{coverageNote(summary) ? ` • ${coverageNote(summary)}` : ""}
            </span>
          </div>
        }
      />

      <LedgerStats
        stats={[
          {
            label: "اليوم الجاري",
            value: summary.open ? summary.open.employee : "لا توجد",
            hint: summary.open ? `بدأ ${fmtTime(summary.open.date)} برصيد ${fmtMoney(summary.open.openingCash)}` : "ابدأ اليوم لبدء البيع",
          },
          { label: "رصيد نهاية اليوم", value: fmtMoneyOrDash(summary.open?.closingBalance), hint: "رصيد البداية + الفواتير − المرتجعات", accent: true },
          { label: "إجمالي المبيعات", value: fmtMoney(summary.salesTotal), hint: [`${fmtInt(summary.closedCount)} يوم مغلق`, coverageNote(summary)].filter(Boolean).join(" • ") },
          { label: "إجمالي المرتجعات", value: fmtMoney(summary.returnsTotal), hint: ["فواتير الإرجاع", coverageNote(summary)].filter(Boolean).join(" • ") },
        ]}
      />

      <ShiftOpenDialog open={openDialog} onOpenChange={(v) => { setOpenDialog(v); if (!v) openShift.reset(); }} onSubmit={submitOpen} pending={openShift.isPending} error={messageOf(openShift.error)} />
      <ShiftCloseDialog open={Boolean(closing)} onOpenChange={(v) => { if (!v) { setClosing(null); closeShift.reset(); } }} shift={closing} heldCount={heldCount.data ?? 0} preview={preview.data} previewLoading={preview.isLoading} onSubmit={submitClose} pending={closeShift.isPending} error={messageOf(closeShift.error) || (preview.error ? messageOf(preview.error) : null)} />
      <ShiftDetailsDialog open={Boolean(details)} onOpenChange={(open) => !open && setDetails(null)} shift={details} />
      <DayReport open={Boolean(report)} onOpenChange={(open) => !open && setReport(null)} shift={report} />
    </LedgerPage>
  );
}