import { useState } from "react";
import { ArrowLeftRight, Clock, Unlock } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import { Image } from "@/cashier/components/ui/image";
import DataTable from "@/cashier/components/ui-kit/DataTable";
import LedgerPage from "@/cashier/components/ui-kit/LedgerPage";
import LedgerStats from "@/cashier/components/ui-kit/LedgerStats";
import PageHero from "@/cashier/components/ui-kit/PageHero";
import ShiftOpenDialog from "@/cashier/components/shifts/ShiftOpenDialog";
import CashMovementDialog from "@/cashier/components/shifts/CashMovementDialog";
import ManagerApprovalDialog from "@/cashier/components/shifts/ManagerApprovalDialog";
import { approvalFailure, approvalReason, needsApproval } from "@/cashier/api/approval";
import { withApproval } from "@/cashier/api/posApi";
import ShiftCloseDialog from "@/cashier/components/shifts/ShiftCloseDialog";
import ShiftDetailsDialog from "@/cashier/components/shifts/ShiftDetailsDialog";
import ShiftFilters from "@/cashier/components/shifts/ShiftFilters";
import shiftColumns from "@/cashier/components/shifts/shiftColumns";
import { BTN, BTN_PRIMARY, LEDGER, LEDGER_FOOTER, LEDGER_TOOLBAR } from "@/cashier/components/ui-kit/ledgerStyles";
import { shiftsSummary } from "@/cashier/lib/storeOpsData";
import { useCashMovement, useClosePreview, useCloseShift, useHeldCount, useOpenShift, useShifts } from "@/cashier/api/useShifts";
import { useAuth } from "@/lib/AuthContext";
import { fmtInt, fmtMoney, fmtTime } from "@/cashier/lib/format";


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
  const { data: rows = [], isLoading, error: loadError, refetch } = useShifts({ employees: user?.id ? { [user.id]: user.full_name || user.email } : {} });
  const openShift = useOpenShift();
  const closeShift = useCloseShift();
  const cashMovement = useCashMovement();
  const [movementOpen, setMovementOpen] = useState(false);
  // A cash-out above the till's limit waits here for a manager. The request is kept as it was sent
  // (same intent), so the approved retry is the same tap, not a second movement.
  const [pendingApproval, setPendingApproval] = useState(null);
  const [employeeFilter, setEmployeeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [openDialog, setOpenDialog] = useState(false);
  const [closing, setClosing] = useState(null);
  const [details, setDetails] = useState(null);
  const preview = useClosePreview(closing?.id, Boolean(closing));
  const heldCount = useHeldCount(closing?.id, Boolean(closing));

  const summary = shiftsSummary(rows);
  const filtered = rows.filter((r) => {
    if (employeeFilter && r.employee !== employeeFilter) return false;
    if (statusFilter && r.status !== statusFilter) return false;
    return true;
  });

  function submitOpen({ openingCash }) {
    openShift.mutate(
      { openingCash },
      {
        onSuccess: () => {
          setOpenDialog(false);
          toast.success(`تم فتح الوردية برصيد ${fmtMoney(openingCash)}`);
        },
      },
    );
  }

  function sendMovement(request, approval) {
    const shift = summary.open;
    const intent = approval ? withApproval(request.intent, approval) : request.intent;
    cashMovement.mutate(
      { sessionId: shift.id, direction: request.direction, reason: request.reason, amount: request.amount, intent },
      {
        onSuccess: () => {
          setPendingApproval(null);
          setMovementOpen(false);
          toast.success(`تم تسجيل الحركة ${fmtMoney(Number(request.amount))} على الوردية ${shift.number}`);
        },
        onError: (error) => {
          if (needsApproval(error) && !approval) setPendingApproval({ request, reason: approvalReason(error) });
        },
      },
    );
  }

  function submitMovement(request) {
    sendMovement(request);
  }

  function submitClose({ actual }) {
    const shift = closing;
    closeShift.mutate(
      { sessionId: shift.id, countedCash: actual },
      {
        onSuccess: (closed) => {
          const diff = Number(closed?.variance ?? 0);
          setClosing(null);
          toast.success(`تم إغلاق الوردية ${shift.number} — ${diff === 0 ? "الخزنة مطابقة" : `فرق ${fmtMoney(diff)}`}`);
        },
      },
    );
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
          <Button className={BTN} disabled={!summary.open} title={summary.open ? "" : "لا توجد وردية مفتوحة"} onClick={() => setMovementOpen(true)}>
            <ArrowLeftRight />
            حركة نقدية
          </Button>
          <Button className={BTN_PRIMARY} disabled={Boolean(summary.open)} onClick={() => setOpenDialog(true)}>
            <Unlock />
            فتح وردية جديدة
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

      <CashMovementDialog
        open={movementOpen}
        onOpenChange={(v) => { setMovementOpen(v); if (!v) cashMovement.reset(); }}
        shift={summary.open}
        expectedCash={summary.open?.expected}
        onSubmit={submitMovement}
        pending={cashMovement.isPending}
        error={needsApproval(cashMovement.error) ? null : messageOf(cashMovement.error)}
      />
      <ManagerApprovalDialog
        open={Boolean(pendingApproval)}
        reason={pendingApproval?.reason}
        pending={cashMovement.isPending}
        error={pendingApproval && cashMovement.error && !needsApproval(cashMovement.error) ? approvalFailure(cashMovement.error) : null}
        onCancel={() => { setPendingApproval(null); cashMovement.reset(); }}
        onApprove={(approval) => sendMovement(pendingApproval.request, approval)}
      />
      <ShiftOpenDialog open={openDialog} onOpenChange={(v) => { setOpenDialog(v); if (!v) openShift.reset(); }} onSubmit={submitOpen} pending={openShift.isPending} error={messageOf(openShift.error)} />
      <ShiftCloseDialog open={Boolean(closing)} onOpenChange={(v) => { if (!v) { setClosing(null); closeShift.reset(); } }} shift={closing} heldCount={heldCount.data ?? 0} preview={preview.data} previewLoading={preview.isLoading} onSubmit={submitClose} pending={closeShift.isPending} error={messageOf(closeShift.error) || (preview.error ? messageOf(preview.error) : null)} />
      <ShiftDetailsDialog open={Boolean(details)} onOpenChange={(open) => !open && setDetails(null)} shift={details} />
    </LedgerPage>
  );
}