import { useSearchParams } from "react-router-dom";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAuth } from "@/lib/AuthContext";
import ReturnHeaderBar from "@/cashier/components/returns/ReturnHeaderBar";
import ExchangeInvoiceSearch from "@/cashier/components/exchanges/ExchangeInvoiceSearch";
import PendingRefundsPanel from "@/cashier/components/returns/PendingRefundsPanel";
import { applyRejectedRefund, mergePendingRefunds, withoutPendingRefund } from "@/cashier/api/pendingRefunds";
import ReturnOriginalTable from "@/cashier/components/returns/ReturnOriginalTable";
import ReturnTotalsBar from "@/cashier/components/returns/ReturnTotalsBar";
import ExchangeNewItemsTable from "@/cashier/components/exchanges/ExchangeNewItemsTable";
import ExchangeSettlementBar from "@/cashier/components/exchanges/ExchangeSettlementBar";
import ExchangeActionsBar from "@/cashier/components/exchanges/ExchangeActionsBar";
import ConfirmDialog from "@/cashier/components/ui-kit/ConfirmDialog";
import useFillRowCount from "@/cashier/hooks/use-fill-row-count";
import { fromMinor, toMinor } from "@/cashier/api/money";
import { fingerprint as fingerprintOf } from "@/cashier/api/intentStore";
import { newIntent, posApi } from "@/cashier/api/posApi";
import WorkingSessionGate from "@/cashier/components/pos/WorkingSessionGate";
import { RECEIPT_SEARCH_MIN, useReceiptSearch, useReturnPolicy, useReturnableSales, useSessionCatalog } from "@/cashier/api/usePosSale";
import { searchCatalog } from "@/cashier/api/catalogAdapter";
import { estimateRefund, returnableLines, sendReturn, setLineCondition, setLineRestock, setQty, tableLine } from "@/cashier/api/returnPlan";
import { addReplacement, previewTotal, removeReplacement, setReplacementQty, useExchangeQuote } from "@/cashier/api/exchangeCart";
import { differenceMinor, exchangeErrorMessage, exchangeRequest, settlementSummary } from "@/cashier/api/exchangePlan";
import { buildTender, defaultTender } from "@/cashier/api/tenderPlan";


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

export default function ExchangePage() {
  return <WorkingSessionGate>{({ session }) => <ExchangeScreen session={session} />}</WorkingSessionGate>;
}

function ExchangeScreen({ session }) {
  const qc = useQueryClient();
  const { user } = useAuth();
  const { invoice: invoiceParam } = Object.fromEntries(useSearchParams()[0]);
  const salesQuery = useReturnableSales(session.id);
  const sales = useMemo(() => (salesQuery.data ?? []).map(asInvoice), [salesQuery.data]);
  const catalogQuery = useSessionCatalog(session.id); // this till's items, price and warehouse stock, like the sales screen
  const catalog = useMemo(() => catalogQuery.data ?? [], [catalogQuery.data]);

  const [invoice, setInvoice] = useState(null);
  const [lines, setLines] = useState([]); // lines coming back (same model as a return)
  const [newLines, setNewLines] = useState([]); // replacement lines
  const [invoiceTerm, setInvoiceTerm] = useState("");
  const [term, setTerm] = useState("");
  const [error, setError] = useState("");
  const [termError, setTermError] = useState("");
  // Why the difference could not be taken/returned. The reset below always referenced it, but the
  // state itself was never declared, so opening the exchange screen threw "setPayError is not
  // defined" and nothing rendered at all.
  const [payError, setPayError] = useState(null);
  const [restockChoice, setRestock] = useState(null); // null = the shop's own default (shown and applied)
  const [reason, setReason] = useState(null);
  const [tenderLines, setTenderLines] = useState([]); // how the customer pays the difference
  const [refundMethod, setRefundMethod] = useState(""); // "" = the tenders the sale actually collected
  const rules = session.tender; // this till's own tender rules: methods, references, split
  const policy = useReturnPolicy(session.id).data;
  const restock = restockChoice ?? policy?.restock_default ?? true;
  const [busy, setBusy] = useState(false);
  // Card reversals the terminal still has to confirm. Loaded on mount so a reload does not lose a
  // promise made before it, and appended from the exchange's own answer.
  const [pendingRefunds, setPendingRefunds] = useState([]);
  const [dialog, setDialog] = useState(null); // cancel
  const intentRef = useRef(null); // one intent per deliberate exchange (+ its payment): a retry replays, never double-charges
  const intentFor = useRef("");
  const gridRef = useRef(null);
  const actionsRef = useRef(null);
  const fillRows = useFillRowCount({ areaRef: gridRef, bottomRef: actionsRef });

  const key = invoiceTerm.trim().toLowerCase();
  // The server finds a sale on ANY shift; wait for a pause in typing so each keystroke is not a request.
  const [searchTerm, setSearchTerm] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setSearchTerm(invoiceTerm), 300);
    return () => clearTimeout(t);
  }, [invoiceTerm]);
  const remote = useReceiptSearch(searchTerm);
  const remoteSales = useMemo(() => (remote.data ?? []).map(asInvoice), [remote.data]);
  const local = key ? sales.filter((s) => s.number.toLowerCase().includes(key) || s.detail.lines.some((l) => String(l.sku ?? "").toLowerCase().includes(key))) : sales;
  const seen = new Set(local.map((s) => s.id));
  const matches = [...local, ...(key ? remoteSales.filter((s) => !seen.has(s.id)) : [])].slice(0, 6);
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
  const shownNew = newLines.length ? Number(quote.total) : 0;
  const hasDraft = !!invoice || newLines.length > 0;
  const recording = Boolean(rules?.take_payments);
  const kind = diffMinor > 0 ? "pay" : diffMinor < 0 ? "refund" : "even";
  const tenderPlan =
    recording && kind === "pay"
      ? buildTender(rules, fromMinor(diffMinor), tenderLines)
      : { ok: true, payload: {} };
  const canComplete =
    !!invoice && backTotals.pieces > 0 && newLines.length > 0 && quoteReady && !busy && tenderPlan.ok;

  // The key follows the EXACT body that will be sent, not a hand-picked list of fields. The list
  // used to leave out the piece condition, the tender lines and the refund method, so a cashier who
  // corrected any of them after a refusal kept the old key and got 409 for reusing it with a
  // different body. Deriving it from the body means a new field can never be forgotten again.
  const request = useMemo(() => {
    if (!invoice) return null;
    try {
      return exchangeRequest(invoice.detail, lines, newLines, {
        restock: restockChoice ?? undefined,
        reason,
        rules,
        differenceMinor: diffMinor,
        tenderLines,
        refundMethod: refundMethod || null,
      });
    } catch {
      return null; // incomplete draft: there is no request to fingerprint
    }
  }, [invoice, lines, newLines, restockChoice, reason, rules, diffMinor, tenderLines, refundMethod]);
  const requestPrint = request ? fingerprintOf(request) : "";
  useEffect(() => {
    if (intentFor.current !== requestPrint) {
      intentRef.current = null;
      intentFor.current = requestPrint;
    }
  }, [requestPrint]);

  // When the difference changes (a line added, a quantity moved) the tender that covered the old
  // amount is meaningless: refill it with the new amount owed, on the till's first method.
  useEffect(() => {
    if (!recording || diffMinor <= 0) {
      setTenderLines([]);
      return;
    }
    setTenderLines(defaultTender(rules, fromMinor(diffMinor)));
  }, [recording, diffMinor, rules]);

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
    setRestock(null);
    setReason(null);
    setNewLines([]);
    setInvoiceTerm("");
    setTerm("");
    setError("");
    setTermError("");
    setPayError(null);
    setTenderLines([]);
    setRefundMethod("");
    intentRef.current = null;
  }
  function submitSearch() {
    const clean = invoiceTerm.trim().toLowerCase();
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

  async function send() {
    if (busy) return;
    setBusy(true);
    try {
      const req =
        request ??
        exchangeRequest(invoice.detail, lines, newLines, {
          restock: restockChoice ?? undefined,
          reason,
          rules,
          differenceMinor: diffMinor,
          tenderLines,
          refundMethod: refundMethod || null,
        });
      intentRef.current ??= newIntent();
      const res = await sendReturn(() => posApi.exchange(session.id, req, intentRef.current)); // same intent re-sent while the first is still running -> wait, then replay
      // The money is the server's answer, not the screen's arithmetic: it knows which tenders the
      // original sale collected and how much of each was still refundable.
      toast.success(`تم الاستبدال ${res.new_receipt_number}. ${settlementSummary(res)}`, { duration: 12000 });
      // Merge, never replace: an older card reversal may still be waiting for its terminal.
      setPendingRefunds((prev) => mergePendingRefunds(prev, res?.awaiting_confirmation));
      intentRef.current = null;
      setDialog(null);
      await qc.invalidateQueries({ queryKey: ["cashier"] });
      resetDraft();
    } catch (e) {
      const m = exchangeErrorMessage(e);
      setError(m);
      // Next to the button the cashier just pressed, not only in the search card above.
      setPayError(m);
      toast.error(m);
    } finally {
      setBusy(false);
    }
  }
  function onComplete() {
    if (!canComplete) return;
    send();
  }
  const paramSearch = useReceiptSearch(invoiceParam ?? "");
  useEffect(() => {
    if (!invoiceParam || invoice) return;
    const want = invoiceParam.toLowerCase();
    const found = [...sales, ...(paramSearch.data ?? []).map(asInvoice)].find((s) => s.number.toLowerCase() === want);
    if (found) return selectInvoice(found);
    if (salesQuery.isLoading || paramSearch.isLoading) return; // still looking: do not say "not found" yet
    setError(`لا توجد فاتورة بيع بالرقم ${invoiceParam}`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      if (e.key === "F2" && canComplete && dialog === null) {
        e.preventDefault();
        onComplete();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className="animate-fade-up flex h-full min-h-0 flex-col gap-2 overflow-hidden">
      <ReturnHeaderBar title="تسجيل استبدال" numberLabel="رقم الاستبدال" employee={user?.full_name || user?.email || ""} />
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
      <div ref={gridRef} className="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)_minmax(0,1fr)] gap-2 2xl:grid-cols-2 2xl:grid-rows-1">
        <div className="flex min-h-0 flex-col gap-1.5">
          <ReturnOriginalTable invoice={invoice} lines={tableLines} onStart={start} onQty={setLineQty} onQtyStep={step} onCancel={cancelLine} onRestock={setPieceRestock} wholeRestock={restock} totals={backTotals} minRows={fillRows} />
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
            lines={lines}
            onCondition={(variantId, condition) => setLines((p) => setLineCondition(p, variantId, condition))}
            exchangedValue={backTotals.value}
            newValue={shownNew}
            difference={Number(fromMinor(diffMinor))}
            loading={newLines.length > 0 && quote.loading}
            error={quote.error}
            restock={restock}
            onRestockChange={(v) => { setRestock(v); setLines((p) => p.map((l) => ({ ...l, restock: null }))); }}
            reasons={policy?.reasons}
            reason={reason}
            onReasonChange={setReason}
            rules={rules}
            tenderLines={tenderLines}
            onTenderChange={setTenderLines}
            refundMethod={refundMethod}
            onRefundMethodChange={setRefundMethod}
          />
        </div>
      </div>
      <div ref={actionsRef}>
        {payError ? (
          <p role="alert" className="px-3 pb-1 text-center text-[11px] font-semibold text-rose-600">
            {payError}
          </p>
        ) : null}
        {!tenderPlan.ok && invoice && newLines.length > 0 ? (
          <p role="alert" className="px-3 pb-1 text-center text-[11px] font-semibold text-rose-600">
            {tenderPlan.message}
          </p>
        ) : null}
        <ExchangeActionsBar canComplete={canComplete} hasDraft={hasDraft} busy={busy} label="إتمام الاستبدال" onComplete={onComplete} onCancel={() => setDialog("cancel")} />
      </div>
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
