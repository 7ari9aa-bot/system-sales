import { useNavigate, useSearchParams } from "react-router-dom";
import { Link } from "react-router-dom";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { TriangleAlert } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import { useAuth } from "@/lib/AuthContext";
import ReturnHeaderBar from "@/cashier/components/returns/ReturnHeaderBar";
import ExchangeInvoiceSearch from "@/cashier/components/exchanges/ExchangeInvoiceSearch";
import ReturnOriginalTable from "@/cashier/components/returns/ReturnOriginalTable";
import ReturnItemsTable from "@/cashier/components/returns/ReturnItemsTable";
import ReturnTotalsBar from "@/cashier/components/returns/ReturnTotalsBar";
import ReturnSettlementBar from "@/cashier/components/returns/ReturnSettlementBar";
import ReturnActionsBar from "@/cashier/components/returns/ReturnActionsBar";
import ConfirmDialog from "@/cashier/components/ui-kit/ConfirmDialog";
import useFillRowCount from "@/cashier/hooks/use-fill-row-count";
import { fmtMoney } from "@/cashier/lib/format";
import { newIntent, posApi } from "@/cashier/api/posApi";
import { useShiftState } from "@/cashier/api/useShifts";
import { useReturnableSales } from "@/cashier/api/usePosSale";
import { estimateRefund, returnErrorMessage, returnRequest, returnableLines, sendReturn, setQty, tableLine } from "@/cashier/api/returnPlan";

const asInvoice = (d) => ({
  id: d.receipt.id,
  number: d.receipt.number,
  date: d.receipt.issued_at,
  total: Number(d.order.grand_total),
  pieces: (d.lines ?? []).reduce((s, l) => s + Number(l.quantity), 0),
  customerName: "عميل نقدي",
  customerPhone: "",
  detail: d,
});

function NoShift() {
  return (
    <div className="animate-fade-up mx-auto mt-16 flex max-w-md flex-col items-center gap-3 rounded-2xl border border-border bg-card p-8 text-center">
      <TriangleAlert className="h-7 w-7 text-amber-600" aria-hidden="true" />
      <p className="text-sm font-semibold" role="status">لا توجد وردية مفتوحة. المرتجع يتم على الوردية المفتوحة التي بيعت فيها الفاتورة.</p>
      <Button asChild><Link to="/cashier/shifts">الذهاب إلى الورديات</Link></Button>
    </div>
  );
}

export default function NewReturnPage() {
  const shift = useShiftState({ canConfigure: false });
  if (shift.isLoading) return <p className="p-8 text-center text-sm text-muted-foreground" role="status">جارٍ التحميل…</p>;
  if (shift.data?.status !== "open") return <NoShift />;
  return <ReturnScreen session={shift.data.session} />;
}

function ReturnScreen({ session }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { user } = useAuth();
  const { invoice: invoiceParam } = Object.fromEntries(useSearchParams()[0]);
  const salesQuery = useReturnableSales(session.id);
  const sales = useMemo(() => (salesQuery.data ?? []).map(asInvoice), [salesQuery.data]);

  const [invoice, setInvoice] = useState(null);
  const [lines, setLines] = useState([]);
  const [term, setTerm] = useState("");
  const [error, setError] = useState("");
  const [restock, setRestock] = useState(true);
  const [busy, setBusy] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const intentRef = useRef(null); // one intent per deliberate return: a retry after a network drop replays, never double-refunds
  const gridRef = useRef(null);
  const actionsRef = useRef(null);
  const fillRows = useFillRowCount({ areaRef: gridRef, bottomRef: actionsRef });

  const key = term.trim().toLowerCase();
  const matches = (key ? sales.filter((s) => s.number.toLowerCase().includes(key) || s.detail.lines.some((l) => String(l.sku ?? "").toLowerCase().includes(key))) : sales).slice(0, 6);
  const quickPicks = sales.filter((s) => s.detail.lines.some((l) => Number(l.quantity) - Number(l.returned_qty ?? 0) > 0)).slice(0, 3);

  const tableLines = useMemo(() => lines.map(tableLine), [lines]);
  const pickedLines = tableLines.filter((l) => l.returnQty > 0);
  const refund = invoice ? estimateRefund(invoice.detail, lines) : "0.00";
  const totals = { pieces: pickedLines.reduce((s, l) => s + l.returnQty, 0), value: Number(refund) };
  const hasDraft = !!invoice || pickedLines.length > 0;
  const canComplete = !!invoice && pickedLines.length > 0 && !busy;

  function selectInvoice(inv) {
    setInvoice(inv);
    setLines(returnableLines(inv.detail));
    setTerm(inv.number);
    setError("");
    intentRef.current = null;
    toast.success(`تم تحميل الفاتورة ${inv.number}`);
  }
  function resetDraft() {
    setInvoice(null);
    setLines([]);
    setTerm("");
    setError("");
    intentRef.current = null;
  }
  function submitSearch() {
    const clean = term.trim().toLowerCase();
    if (!clean) return setError("اكتب رقم الفاتورة أو كود الصنف أولًا");
    const exact = sales.find((s) => s.number.toLowerCase() === clean);
    if (exact) return selectInvoice(exact);
    if (matches.length === 1) return selectInvoice(matches[0]);
    setError(matches.length ? "أكثر من فاتورة مطابقة. اختر من القائمة" : "لا توجد فاتورة بهذا الرقم في الوردية المفتوحة. المرتجع يتم على نفس وردية البيع.");
  }
  const start = (k) => setLines((p) => setQty(p, k, 1));
  const cancelLine = (k) => setLines((p) => setQty(p, k, 0));
  const setLineQty = (k, v) => setLines((p) => setQty(p, k, Math.max(1, Number(v) || 1)));
  const step = (k, d) => setLines((p) => setQty(p, k, Math.max(1, (p.find((l) => l.variantId === k)?.returnQty ?? 1) + d)));

  async function confirmReturn() {
    if (!canComplete) return;
    setBusy(true);
    try {
      const req = returnRequest(invoice.detail, lines, { restock });
      intentRef.current ??= newIntent();
      const intent = intentRef.current;
      const res = await sendReturn(() => posApi.returnSale(session.id, req, intent));
      toast.success(`تم اعتماد المرتجع ${res.receipt_number}. رد ${fmtMoney(Number(res.refunded_total))} للعميل`);
      intentRef.current = null;
      await Promise.all([qc.invalidateQueries({ queryKey: ["cashier"] })]);
      resetDraft();
    } catch (e) {
      setError(returnErrorMessage(e));
      toast.error(returnErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!invoiceParam || invoice || !sales.length) return;
    const found = sales.find((s) => s.number.toLowerCase() === invoiceParam.toLowerCase());
    if (found) selectInvoice(found);
    else setError(`الفاتورة ${invoiceParam} ليست ضمن الوردية المفتوحة. المرتجع يتم على نفس وردية البيع.`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invoiceParam, sales]);

  useEffect(() => {
    function onKey(e) {
      if (e.key === "F2" && canComplete) {
        e.preventDefault();
        confirmReturn();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className="animate-fade-up flex flex-col gap-2 pb-2">
      <ReturnHeaderBar employee={user?.full_name || user?.email || ""} />
      <ExchangeInvoiceSearch
        term={term}
        onTermChange={(v) => { setTerm(v); setError(""); }}
        onSubmit={submitSearch}
        error={error}
        invoice={invoice}
        matches={matches}
        quickPicks={quickPicks}
        onPick={selectInvoice}
        onClear={resetDraft}
      />
      {salesQuery.isError ? <p role="alert" className="text-xs font-semibold text-rose-600">تعذّر تحميل فواتير الوردية</p> : null}
      <div ref={gridRef} className="grid gap-2 2xl:grid-cols-2">
        <div className="flex min-h-0 flex-col gap-1.5">
          <ReturnOriginalTable invoice={invoice} lines={tableLines} onStart={start} onQty={setLineQty} onQtyStep={step} onCancel={cancelLine} totals={totals} minRows={fillRows} />
          <ReturnTotalsBar totals={totals} />
        </div>
        <div className="flex min-h-0 flex-col gap-1.5">
          <ReturnItemsTable lines={pickedLines} totals={totals} onQty={setLineQty} onQtyStep={step} onRemove={(l) => cancelLine(l.key)} minRows={fillRows} />
          <ReturnSettlementBar value={totals.value} restock={restock} onRestockChange={setRestock} />
        </div>
      </div>
      <div ref={actionsRef}>
        <ReturnActionsBar canComplete={canComplete} hasDraft={hasDraft} onComplete={confirmReturn} onCancel={() => setCancelOpen(true)} />
      </div>
      <ConfirmDialog
        open={cancelOpen}
        onOpenChange={setCancelOpen}
        title="إلغاء عملية المرتجع"
        description="سيتم حذف الفاتورة المختارة والأصناف المحددة في هذه العملية، دون أي تأثير على المخزون أو تسجيل مرتجع."
        confirmLabel="إلغاء العملية"
        onConfirm={() => { resetDraft(); toast.info("تم إلغاء عملية المرتجع"); }}
      />
    </div>
  );
}
