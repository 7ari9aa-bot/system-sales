import { useNavigate, useSearchParams } from "react-router-dom";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAuth } from "@/lib/AuthContext";
import ReturnHeaderBar from "@/cashier/components/returns/ReturnHeaderBar";
import ExchangeInvoiceSearch from "@/cashier/components/exchanges/ExchangeInvoiceSearch";
import ReturnOriginalTable from "@/cashier/components/returns/ReturnOriginalTable";
import ReturnItemsTable from "@/cashier/components/returns/ReturnItemsTable";
import ReturnTotalsBar from "@/cashier/components/returns/ReturnTotalsBar";
import PendingRefundsPanel from "@/cashier/components/returns/PendingRefundsPanel";
import { applyRejectedRefund, mergePendingRefunds, withoutPendingRefund } from "@/cashier/api/pendingRefunds";
import ReturnSettlementBar from "@/cashier/components/returns/ReturnSettlementBar";
import ReturnActionsBar from "@/cashier/components/returns/ReturnActionsBar";
import ConfirmDialog from "@/cashier/components/ui-kit/ConfirmDialog";
import useFillRowCount from "@/cashier/hooks/use-fill-row-count";
import { fmtMoney } from "@/cashier/lib/format";
import { fingerprint as fingerprintOf } from "@/cashier/api/intentStore";
import { newIntent, posApi } from "@/cashier/api/posApi";
import WorkingSessionGate from "@/cashier/components/pos/WorkingSessionGate";
import { RECEIPT_SEARCH_MIN, useReceiptSearch, useReturnPolicy, useReturnableSales } from "@/cashier/api/usePosSale";
import { estimateRefund, returnErrorMessage, returnRequest, returnSettlementSummary, returnableLines, sendReturn, setLineCondition, setLineRestock, setQty, tableLine } from "@/cashier/api/returnPlan";

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

export default function NewReturnPage() {
  return <WorkingSessionGate>{({ session }) => <ReturnScreen session={session} />}</WorkingSessionGate>;
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
  // null = the cashier has not touched it: the box shows the shop's own default, and the server
  // applies that same default, so what is shown is what happens.
  const [restockChoice, setRestock] = useState(null);
  const [reason, setReason] = useState(null);
  const policy = useReturnPolicy(session.id).data;
  const restock = restockChoice ?? policy?.restock_default ?? true;
  const [busy, setBusy] = useState(false);
  // The card/wallet part of the refund that the terminal still has to confirm. Kept after the draft
  // resets, because the cashier has to walk to the machine and come back with the reference.
  const [pendingRefunds, setPendingRefunds] = useState([]);
  const [cancelOpen, setCancelOpen] = useState(false);
  const intentRef = useRef(null); // one intent per deliberate return: a retry after a network drop replays, never double-refunds
  const intentFor = useRef("");
  const gridRef = useRef(null);
  const actionsRef = useRef(null);
  const fillRows = useFillRowCount({ areaRef: gridRef, bottomRef: actionsRef });

  const key = term.trim().toLowerCase();
  // The server finds a sale on ANY shift; wait for a pause in typing so each keystroke is not a request.
  const [searchTerm, setSearchTerm] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setSearchTerm(term), 300);
    return () => clearTimeout(t);
  }, [term]);
  const remote = useReceiptSearch(searchTerm);
  const remoteSales = useMemo(() => (remote.data ?? []).map(asInvoice), [remote.data]);
  const local = key ? sales.filter((s) => s.number.toLowerCase().includes(key) || s.detail.lines.some((l) => String(l.sku ?? "").toLowerCase().includes(key))) : sales;
  const seen = new Set(local.map((s) => s.id));
  const matches = [...local, ...(key ? remoteSales.filter((s) => !seen.has(s.id)) : [])].slice(0, 6);
  const quickPicks = sales.filter((s) => s.detail.lines.some((l) => Number(l.quantity) - Number(l.returned_qty ?? 0) > 0)).slice(0, 3);

  const tableLines = useMemo(() => lines.map(tableLine), [lines]);
  const pickedLines = tableLines.filter((l) => l.returnQty > 0);
  const refund = invoice ? estimateRefund(invoice.detail, lines) : "0.00";
  const totals = { pieces: pickedLines.reduce((s, l) => s + l.returnQty, 0), value: Number(refund) };
  const hasDraft = !!invoice || pickedLines.length > 0;
  const canComplete = !!invoice && pickedLines.length > 0 && !busy;

  // The key follows the EXACT body that will be sent, not a hand-picked list of fields. The list
  // used to leave out the piece condition, so a cashier who picked "damaged" after a refusal kept
  // the old key and the server answered 409 for reusing it with a different body — a refusal the
  // user could never get out of. Building it from the body means a new field can never be missed.
  const request = useMemo(() => {
    if (!invoice) return null;
    try {
      return returnRequest(invoice.detail, lines, { restock: restockChoice ?? undefined, reason });
    } catch {
      return null; // nothing picked yet: there is no request to fingerprint
    }
  }, [invoice, lines, restockChoice, reason]);
  const requestPrint = request ? fingerprintOf(request) : "";
  useEffect(() => {
    if (intentFor.current !== requestPrint) {
      intentRef.current = null;
      intentFor.current = requestPrint;
    }
  }, [requestPrint]);

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
    setRestock(null);
    setReason(null);
    setTerm("");
    setError("");
    intentRef.current = null;
  }
  function submitSearch() {
    const clean = term.trim().toLowerCase();
    if (!clean) return setError("اكتب رقم الفاتورة أو كود الصنف أولًا");
    const exact = [...sales, ...remoteSales].find((s) => s.number.toLowerCase() === clean);
    if (exact) return selectInvoice(exact);
    if (matches.length === 1) return selectInvoice(matches[0]);
    if (matches.length) return setError("أكثر من فاتورة مطابقة. اختر من القائمة");
    if (clean.length < RECEIPT_SEARCH_MIN) return setError(`اكتب ${RECEIPT_SEARCH_MIN} أحرف على الأقل من رقم الفاتورة`);
    if (remote.isFetching || searchTerm.trim().toLowerCase() !== clean) return setError("جارٍ البحث… أعد المحاولة بعد لحظة");
    setError("لا توجد فاتورة بيع بهذا الرقم");
  }
  const start = (k) => setLines((p) => setQty(p, k, 1));
  const cancelLine = (k) => setLines((p) => setQty(p, k, 0));
  const setPieceRestock = (k, v) => setLines((p) => setLineRestock(p, k, v));
  const setLineCondition_ = (key, condition) => setLines((p) => setLineCondition(p, key, condition));
  const setLineQty = (k, v) => setLines((p) => setQty(p, k, Math.max(1, Number(v) || 1)));
  const step = (k, d) => setLines((p) => setQty(p, k, Math.max(1, (p.find((l) => l.variantId === k)?.returnQty ?? 1) + d)));

  async function confirmReturn() {
    if (!canComplete || busy) return;
    setBusy(true);
    try {
      const req = request ?? returnRequest(invoice.detail, lines, { restock: restockChoice ?? undefined, reason });
      intentRef.current ??= newIntent();
      const res = await sendReturn(() => posApi.returnSale(session.id, req, intentRef.current));
      toast.success(`تم تسجيل المرتجع ${res.receipt_number}. ${returnSettlementSummary(res)}`, { duration: 12000 });
      // Merge, never replace: an older card reversal may still be waiting for its terminal.
      setPendingRefunds((prev) => mergePendingRefunds(prev, res?.awaiting_confirmation));
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

  // A link from the sales log carries an invoice number that may belong to an earlier shift.
  const paramSearch = useReceiptSearch(invoiceParam && !invoice ? invoiceParam : "");
  useEffect(() => {
    if (!invoiceParam || invoice || salesQuery.isLoading || paramSearch.isLoading) return;
    const wanted = invoiceParam.toLowerCase();
    const pool = [...sales, ...(paramSearch.data ?? []).map(asInvoice)];
    const found = pool.find((s) => s.number.toLowerCase() === wanted);
    if (found) selectInvoice(found);
    else setError(`لم نجد فاتورة بيع بالرقم ${invoiceParam}`);
     
  }, [invoiceParam, sales, paramSearch.data, paramSearch.isLoading, salesQuery.isLoading]);

  // The promise outlives the page: a card reversal taken before a reload is still owed.
  useEffect(() => {
    let alive = true;
    posApi
      .listPendingRefunds()
      .then((rows) => {
        if (alive) setPendingRefunds(rows ?? []);
      })
      .catch(() => {}); // a read failure must not block the till
    return () => {
      alive = false;
    };
  }, []);

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
    <div className="animate-fade-up flex h-full min-h-0 flex-col gap-2 overflow-hidden">
      <ReturnHeaderBar employee={user?.full_name || user?.email || ""} />
      <PendingRefundsPanel
        sessionId={session?.id ?? null}
        pending={pendingRefunds}
        onConfirmed={(res) =>
          setPendingRefunds((prev) => withoutPendingRefund(prev, res.refund_id))
        }
        // The attempt is rejected but the customer was not paid: the follow-up row is the money
        // still owed, and it appears on this screen in the same update.
        onRejected={(res) => setPendingRefunds((prev) => applyRejectedRefund(prev, res))}
      />
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
      <div ref={gridRef} className="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)_minmax(0,1fr)] gap-2 2xl:grid-cols-2 2xl:grid-rows-1">
        <div className="flex min-h-0 flex-col gap-1.5">
          <ReturnOriginalTable invoice={invoice} lines={tableLines} onStart={start} onQty={setLineQty} onQtyStep={step} onCancel={cancelLine} onRestock={setPieceRestock} wholeRestock={restock} totals={totals} minRows={fillRows} />
          <ReturnTotalsBar totals={totals} />
        </div>
        <div className="flex min-h-0 flex-col gap-1.5">
          <ReturnItemsTable lines={pickedLines} totals={totals} onQty={setLineQty} onQtyStep={step} onRemove={(l) => cancelLine(l.key)} onCondition={setLineCondition_} minRows={fillRows} />
          <ReturnSettlementBar value={totals.value} restock={restock} onRestockChange={(v) => { setRestock(v); setLines((p) => p.map((l) => ({ ...l, restock: null }))); }} reasons={policy?.reasons} reason={reason} onReasonChange={setReason} lines={lines} takePayments={session?.tender?.take_payments ?? null} />
        </div>
      </div>
      <div ref={actionsRef}>
        <ReturnActionsBar canComplete={canComplete} hasDraft={hasDraft} onComplete={() => confirmReturn()} onCancel={() => setCancelOpen(true)} />
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
