import { Link, useSearchParams } from "react-router-dom";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { TriangleAlert } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import { useAuth } from "@/lib/AuthContext";
import ReturnHeaderBar from "@/cashier/components/returns/ReturnHeaderBar";
import ExchangeInvoiceSearch from "@/cashier/components/exchanges/ExchangeInvoiceSearch";
import ReturnOriginalTable from "@/cashier/components/returns/ReturnOriginalTable";
import ReturnTotalsBar from "@/cashier/components/returns/ReturnTotalsBar";
import ExchangeNewItemsTable from "@/cashier/components/exchanges/ExchangeNewItemsTable";
import ExchangeSettlementBar from "@/cashier/components/exchanges/ExchangeSettlementBar";
import ExchangeActionsBar from "@/cashier/components/exchanges/ExchangeActionsBar";
import PaymentDialog from "@/cashier/components/pos/PaymentDialog";
import ConfirmDialog from "@/cashier/components/ui-kit/ConfirmDialog";
import useFillRowCount from "@/cashier/hooks/use-fill-row-count";
import { fmtMoney } from "@/cashier/lib/format";
import { fromMinor, toMinor } from "@/cashier/api/money";
import { newIntent, posApi, withApproval } from "@/cashier/api/posApi";
import { approvalFailure, approvalReason, needsApproval } from "@/cashier/api/approval";
import ManagerApprovalDialog from "@/cashier/components/shifts/ManagerApprovalDialog";
import { useShiftState } from "@/cashier/api/useShifts";
import { useCatalog, useReturnableSales } from "@/cashier/api/usePosSale";
import { searchCatalog } from "@/cashier/api/catalogAdapter";
import { estimateRefund, returnableLines, sendReturn, setQty, tableLine } from "@/cashier/api/returnPlan";
import { addReplacement, previewTotal, removeReplacement, setReplacementQty, useExchangeQuote } from "@/cashier/api/exchangeCart";
import { differenceMinor, exchangeErrorMessage, exchangePayment, exchangeRequest, settlementKind } from "@/cashier/api/exchangePlan";


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
      <p className="text-sm font-semibold" role="status">لا توجد وردية مفتوحة. الاستبدال يتم على الوردية المفتوحة التي بيعت فيها الفاتورة.</p>
      <Button asChild><Link to="/cashier/shifts">الذهاب إلى الورديات</Link></Button>
    </div>
  );
}

export default function ExchangePage() {
  const shift = useShiftState({ canConfigure: false });
  if (shift.isLoading) return <p className="p-8 text-center text-sm text-muted-foreground" role="status">جارٍ التحميل…</p>;
  if (shift.data?.status !== "open") return <NoShift />;
  return <ExchangeScreen session={shift.data.session} />;
}

function ExchangeScreen({ session }) {
  const qc = useQueryClient();
  const { user } = useAuth();
  const { invoice: invoiceParam } = Object.fromEntries(useSearchParams()[0]);
  const salesQuery = useReturnableSales(session.id);
  const sales = useMemo(() => (salesQuery.data ?? []).map(asInvoice), [salesQuery.data]);
  const catalogQuery = useCatalog();
  const catalog = useMemo(() => catalogQuery.data ?? [], [catalogQuery.data]);

  const [invoice, setInvoice] = useState(null);
  const [lines, setLines] = useState([]); // lines coming back (same model as a return)
  const [newLines, setNewLines] = useState([]); // replacement lines
  const [invoiceTerm, setInvoiceTerm] = useState("");
  const [term, setTerm] = useState("");
  const [error, setError] = useState("");
  const [termError, setTermError] = useState("");
  const [restock, setRestock] = useState(true);
  const [busy, setBusy] = useState(false);
  const [payError, setPayError] = useState(null);
  const [approval, setApproval] = useState(null); // { payment, reason, error }: waits for a manager, then re-sends the SAME request
  const [dialog, setDialog] = useState(null); // payment | cancel
  const intentRef = useRef(null); // one intent per deliberate exchange (+ its payment): a retry replays, never double-charges
  const intentFor = useRef("");
  const gridRef = useRef(null);
  const actionsRef = useRef(null);
  const fillRows = useFillRowCount({ areaRef: gridRef, bottomRef: actionsRef });

  const key = invoiceTerm.trim().toLowerCase();
  const matches = (key ? sales.filter((s) => s.number.toLowerCase().includes(key) || s.detail.lines.some((l) => String(l.sku ?? "").toLowerCase().includes(key))) : sales).slice(0, 6);
  const quickPicks = sales.filter((s) => s.detail.lines.some((l) => Number(l.quantity) - Number(l.returned_qty ?? 0) > 0)).slice(0, 3);
  const variantMatches = term.trim() ? searchCatalog(catalog, term, 10).filter((v) => v.stock > 0) : [];

  const tableLines = useMemo(() => lines.map(tableLine), [lines]);
  const pickedLines = tableLines.filter((l) => l.returnQty > 0);
  const refund = invoice ? estimateRefund(invoice.detail, lines) : "0.00";
  const backTotals = { pieces: pickedLines.reduce((s, l) => s + l.returnQty, 0), value: Number(refund) };
  const newTotals = { pieces: newLines.reduce((s, l) => s + l.qty, 0), value: previewTotal(newLines) };

  const quote = useExchangeQuote(session.id, newLines);
  const quoteReady = newLines.length > 0 && !quote.loading && !quote.error;
  const diffMinor = invoice && quoteReady ? differenceMinor(invoice.detail, lines, quote.total) : 0;
  const kind = settlementKind(diffMinor);
  const shownNew = newLines.length ? Number(quote.total) : 0;
  const hasDraft = !!invoice || newLines.length > 0;
  const canComplete = !!invoice && backTotals.pieces > 0 && newLines.length > 0 && quoteReady && !busy;

  // A new draft (different lines / quantities) must never reuse the intent of an earlier attempt.
  const fingerprint = JSON.stringify([invoice?.id, lines.map((l) => [l.variantId, l.returnQty]), newLines.map((l) => [l.variantId, l.qty]), restock]);
  useEffect(() => {
    if (intentFor.current !== fingerprint) {
      intentRef.current = null;
      intentFor.current = fingerprint;
    }
  }, [fingerprint]);

  function selectInvoice(inv) {
    setInvoice(inv);
    setLines(returnableLines(inv.detail));
    setInvoiceTerm(inv.number);
    setError("");
    toast.success(`تم تحميل الفاتورة ${inv.number}`);
  }
  function resetDraft() {
    setInvoice(null);
    setLines([]);
    setNewLines([]);
    setInvoiceTerm("");
    setTerm("");
    setError("");
    setTermError("");
    setPayError(null);
    intentRef.current = null;
  }
  function submitSearch() {
    const clean = invoiceTerm.trim().toLowerCase();
    if (!clean) return setError("اكتب رقم الفاتورة أو كود الصنف أولًا");
    const exact = sales.find((s) => s.number.toLowerCase() === clean);
    if (exact) return selectInvoice(exact);
    if (matches.length === 1) return selectInvoice(matches[0]);
    setError(matches.length ? "أكثر من فاتورة مطابقة. اختر من القائمة" : "لا توجد فاتورة بهذا الرقم في الوردية المفتوحة. الاستبدال يتم على نفس وردية البيع.");
  }
  const start = (k) => setLines((p) => setQty(p, k, 1));
  const cancelLine = (k) => setLines((p) => setQty(p, k, 0));
  const setLineQty = (k, v) => setLines((p) => setQty(p, k, Math.max(1, Number(v) || 1)));
  const step = (k, d) => setLines((p) => setQty(p, k, Math.max(1, (p.find((l) => l.variantId === k)?.returnQty ?? 1) + d)));

  function addVariant(variant) {
    const r = addReplacement(newLines, variant);
    if (!r.ok) return toast.warning(r.reason);
    setNewLines(r.lines);
    setTerm("");
    setTermError("");
  }
  function submitTerm() {
    const clean = term.trim();
    if (!clean) return;
    const byCode = catalog.find((v) => v.barcode && v.barcode === clean);
    if (byCode) return addVariant(byCode);
    if (variantMatches.length === 1) return addVariant(variantMatches[0]);
    setTermError(variantMatches.length ? `أكثر من صنف يطابق «${clean}». اختر من النتائج` : `لا يوجد صنف متاح بالباركود أو الاسم «${clean}»`);
  }
  const setNewQty = (id, v) => setNewLines((p) => setReplacementQty(p, id, v));
  const stepNewQty = (id, d) => {
    const l = newLines.find((x) => x.lineId === id);
    if (!l) return;
    if (d > 0 && l.qty >= l.stock) return toast.warning(`المتاح من ${l.name} ${l.stock} قطعة فقط`);
    setNewLines((p) => setReplacementQty(p, id, l.qty + d));
  };

  async function send(payment, managerOk) {
    if (busy) return;
    setBusy(true);
    setPayError(null);
    try {
      const req = exchangeRequest(invoice.detail, lines, newLines, { restock, tenders: payment.tenders, tenderedCash: payment.tenderedCash });
      intentRef.current ??= newIntent();
      const intent = managerOk ? withApproval(intentRef.current, managerOk) : intentRef.current;
      const res = await sendReturn(() => posApi.exchange(session.id, req, intent)); // same intent re-sent while the first is still running -> wait, then replay
      const net = Number(res.net);
      toast.success(
        net > 0 ? `تم الاستبدال ${res.new_receipt_number}. تم تحصيل ${fmtMoney(net)}` : net < 0 ? `تم الاستبدال ${res.new_receipt_number}. رد ${fmtMoney(Math.abs(net))} للعميل` : `تم الاستبدال ${res.new_receipt_number} بدون فرق`,
      );
      intentRef.current = null;
      setApproval(null);
      setDialog(null);
      await qc.invalidateQueries({ queryKey: ["cashier"] });
      resetDraft();
    } catch (e) {
      if (needsApproval(e) && !managerOk) {
        setDialog(null); // the payment box gives way to the manager box; the request is kept as it was
        setApproval({ payment, reason: approvalReason(e), error: null });
      } else if (managerOk) {
        setApproval((a) => ({ ...(a ?? { payment }), error: approvalFailure(e) }));
      } else {
        const m = exchangeErrorMessage(e);
        setPayError(m);
        setError(m);
        toast.error(m);
      }
    } finally {
      setBusy(false);
    }
  }
  function onComplete() {
    if (!canComplete) return;
    if (kind === "pay") return setDialog("payment");
    send({});
  }
  function onPay(rows) {
    const p = exchangePayment(diffMinor, rows);
    if (!p.ok) return setPayError(p.reason);
    send(p);
  }

  useEffect(() => {
    if (!invoiceParam || invoice || !sales.length) return;
    const found = sales.find((s) => s.number.toLowerCase() === invoiceParam.toLowerCase());
    if (found) selectInvoice(found);
    else setError(`الفاتورة ${invoiceParam} ليست ضمن الوردية المفتوحة. الاستبدال يتم على نفس وردية البيع.`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invoiceParam, sales]);

  useEffect(() => {
    function onKey(e) {
      if (e.key === "F2" && canComplete && dialog === null) {
        e.preventDefault();
        onComplete();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className="animate-fade-up flex flex-col gap-2 pb-2">
      <ReturnHeaderBar employee={user?.full_name || user?.email || ""} />
      <ExchangeInvoiceSearch
        term={invoiceTerm}
        onTermChange={(v) => { setInvoiceTerm(v); setError(""); }}
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
          <ReturnOriginalTable invoice={invoice} lines={tableLines} onStart={start} onQty={setLineQty} onQtyStep={step} onCancel={cancelLine} totals={backTotals} minRows={fillRows} />
          <ReturnTotalsBar totals={backTotals} />
        </div>
        <div className="flex min-h-0 flex-col gap-1.5">
          <ExchangeNewItemsTable
            lines={newLines}
            term={term}
            onTermChange={(v) => { setTerm(v); setTermError(""); }}
            onSubmit={submitTerm}
            onQty={setNewQty}
            onQtyStep={stepNewQty}
            onRemove={(l) => setNewLines((p) => removeReplacement(p, l.lineId))}
            matches={variantMatches}
            onPick={addVariant}
            error={termError}
            totals={{ pieces: newTotals.pieces, value: shownNew || newTotals.value }}
            movedPieces={backTotals.pieces}
            minRows={fillRows}
          />
          <ExchangeSettlementBar
            exchangedValue={backTotals.value}
            newValue={shownNew}
            difference={Number(fromMinor(diffMinor))}
            loading={newLines.length > 0 && quote.loading}
            error={quote.error}
            restock={restock}
            onRestockChange={setRestock}
          />
        </div>
      </div>
      <div ref={actionsRef}>
        <ExchangeActionsBar canComplete={canComplete} hasDraft={hasDraft} busy={busy} label={kind === "pay" ? "الدفع وإتمام الاستبدال" : "إتمام الاستبدال"} onComplete={onComplete} onCancel={() => setDialog("cancel")} />
      </div>
      <PaymentDialog
        open={dialog === "payment"}
        onOpenChange={(o) => { setDialog(o ? "payment" : null); if (!o) setPayError(null); }}
        total={fromMinor(Math.max(diffMinor, 0))}
        customerName="فرق الاستبدال"
        onConfirm={onPay}
        pending={busy}
        error={payError}
      />
      <ManagerApprovalDialog
        open={Boolean(approval)}
        reason={approval?.reason}
        pending={busy}
        error={approval?.error}
        onCancel={() => setApproval(null)}
        onApprove={(ok) => send(approval.payment, ok)}
      />
      <ConfirmDialog
        open={dialog === "cancel"}
        onOpenChange={(o) => setDialog(o ? "cancel" : null)}
        title="إلغاء عملية الاستبدال"
        description="سيتم حذف الفاتورة المختارة والأصناف في هذه العملية، دون أي تأثير على المخزون أو تسجيل استبدال."
        confirmLabel="إلغاء العملية"
        onConfirm={() => { resetDraft(); toast.info("تم إلغاء عملية الاستبدال"); }}
      />
    </div>
  );
}
