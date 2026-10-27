import { TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useSearchParams } from "react-router-dom";
import PosHeaderBar from "@/cashier/components/pos/PosHeaderBar";
import PosCustomerFields from "@/cashier/components/pos/PosCustomerFields";
import PosInvoiceTable from "@/cashier/components/pos/PosInvoiceTable";
import PosActionsBar from "@/cashier/components/pos/PosActionsBar";
import PosInvoiceDiscounts from "@/cashier/components/pos/PosInvoiceDiscounts";
import PosInvoiceSummary from "@/cashier/components/pos/PosInvoiceSummary";
import ConfirmSaleDialog from "@/cashier/components/pos/ConfirmSaleDialog";
import ReceiptDialog from "@/cashier/components/pos/ReceiptDialog";
import SuspendedDialog from "@/cashier/components/pos/SuspendedDialog";
import HoldDialog from "@/cashier/components/pos/HoldDialog";
import NoteDialog from "@/cashier/components/pos/NoteDialog";
import ConfirmDialog from "@/cashier/components/ui-kit/ConfirmDialog";
import { Button } from "@/cashier/components/ui/button";
import { CATALOG_KEY, HELD_KEY, SESSION_CATALOG_KEY, fetchSessionCatalog, useCustomerSearch, useHeldCarts, usePosSale, useSessionCatalog, useShiftProfile } from "@/cashier/api/usePosSale";
import { customerBlock } from "@/cashier/api/customerRule";
import WorkingSessionGate from "@/cashier/components/pos/WorkingSessionGate";
import { searchCatalog } from "@/cashier/api/catalogAdapter";
import { posApi } from "@/cashier/api/posApi";
import { useAuth } from "@/lib/AuthContext";
import { clearedIfStill, createScanQueue } from "@/cashier/lib/scanQueue";

// Only methods the backend accepts; the profile's own list narrows this further once loaded.

// مُعرّف ثابت لرسالة الحذف: كل حذف جديد يستبدل الرسالة السابقة، فيكون التراجع لأحدث حذف.
const UNDO_TOAST_ID = "pos-undo-remove";

export default function PosPage() {
  const { user } = useAuth?.() ?? {};
  return <WorkingSessionGate>{({ session }) => <PosScreen user={user} session={session} />}</WorkingSessionGate>;
}

function PosScreen({ user, session }) {
  const qc = useQueryClient();
  const catalogQuery = useSessionCatalog(session.id); // this till's items, price and warehouse stock
  const catalog = useMemo(() => catalogQuery.data ?? [], [catalogQuery.data]);
  const [receipt, setReceipt] = useState(null);
  const [lastReceipt, setLastReceipt] = useState(null);
  const sale = usePosSale({
    sessionId: session.id,
    registerId: session.register_id,
    catalog,
    loadFreshCatalog: async () => (await qc.fetchQuery({ queryKey: SESSION_CATALOG_KEY(session.id), queryFn: () => fetchSessionCatalog(session.id), staleTime: 0 })) ?? [],
    onSold: (r) => {
      setReceipt(r);
      setLastReceipt(r);
      setDialog("receipt");
      qc.invalidateQueries({ queryKey: CATALOG_KEY }); // stock changed
    },
  });
  const { lines } = sale;
  const heldQuery = useHeldCarts(session.id, catalog);
  const [heldBusy, setHeldBusy] = useState(null);
  const [heldError, setHeldError] = useState(null);
  const [holding, setHolding] = useState(false);
  const refreshHeld = () => qc.invalidateQueries({ queryKey: HELD_KEY(session.id) });

  const [barcode, setBarcode] = useState("");
  const [scanError, setScanError] = useState("");
  const [customerName, setCustomerName] = useState("");
  const [customerPhone, setCustomerPhone] = useState("");
  const [pickedCustomer, setPickedCustomer] = useState(null); // a REAL customer; the typed name above is only a label
  const profile = useShiftProfile(session.profile_id);
  const requireCustomer = Boolean(profile.data?.require_customer);
  const customerSearch = useCustomerSearch(pickedCustomer ? "" : customerName);
  const needCustomer = customerBlock({ requireCustomer, customerId: pickedCustomer?.id });
  const [activeLineId, setActiveLineId] = useState(null);
  const [invoiceDiscountPct, setInvoiceDiscountPct] = useState(0);
  const [invoiceDiscountAmt, setInvoiceDiscountAmt] = useState(0);
  // The shift screen links here with ?held=1 to review parked invoices before closing: open that list once.
  const [searchParams, setSearchParams] = useSearchParams();
  const [dialog, setDialog] = useState(() => (searchParams.get("held") === "1" ? "held" : null)); // payment | receipt | cancel | held | note
  useEffect(() => {
    if (searchParams.get("held") === "1") setSearchParams({}, { replace: true });
  }, [searchParams, setSearchParams]);
  const removedRef = useRef(null);

  const cashier = user?.full_name || user?.email || "";
  const hasLines = lines.length > 0;
  const displayCustomer = pickedCustomer?.name || customerName.trim() || "عميل نقدي";
  const quoteReady = hasLines && !sale.quote.loading && !sale.quote.error && !needCustomer;

  // Invoice discount = percentage of the subtotal + a fixed amount, sent to the backend as ONE amount.
  const subtotalNumber = Number(sale.quote.subtotal) || 0;
  // The lines' own discounts are priced first; the invoice discount (percentage + fixed) can only
  // take what is left of the invoice, whatever order the cashier typed things in.
  const lineDiscountsTotal = lines.reduce((sum, l) => sum + (Number(l.discount) || 0), 0);
  useEffect(() => {
    const room = Math.max(0, +(subtotalNumber - lineDiscountsTotal).toFixed(2));
    const fromPct = (subtotalNumber * (Number(invoiceDiscountPct) || 0)) / 100;
    const amount = Math.min(room, +(fromPct + (Number(invoiceDiscountAmt) || 0)).toFixed(2));
    sale.setInvoiceDiscount(amount > 0 ? String(amount) : "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invoiceDiscountPct, invoiceDiscountAmt, subtotalNumber, lineDiscountsTotal]);

  const finalTotals = {
    pieces: lines.reduce((s, l) => s + l.qty, 0),
    subTotal: Number(sale.quote.subtotal) || 0,
    linesDiscount: 0,
    invoiceDiscount: Number(sale.quote.discountTotal) || 0,
    pctDiscount: Number(sale.quote.discountTotal) || 0,
    total: Number(sale.quote.total) || 0,
  };

  function addVariant(variant) {
    const r = sale.add(variant);
    if (!r.ok) {
      setScanError(`${variant.productName}: ${r.reason}`);
      return false;
    }
    setActiveLineId(String(variant.id));
    return true;
  }

  // A scanner fires the next code before the previous answer is back. Codes are handled strictly one after
  // another (a queue), and the field is cleared only if it still holds the code we just handled, so the
  // next scanned code is never wiped by the previous one finishing.
  const scanQueue = useRef(createScanQueue());
  const clearIfStill = (clean) => setBarcode((cur) => clearedIfStill(cur, clean));

  function submitBarcode() {
    const clean = barcode.trim();
    if (!clean) return;
    scanQueue.current.push(() => handleBarcode(clean));
  }

  async function handleBarcode(clean) {
    // 1) a barcode scan is answered by the backend, 2) otherwise it is a name / code search.
    try {
      const scan = await sale.scan(clean);
      if (scan && scan.found === false && scan.refusal) {
        setScanError(scan.refusal); // e.g. "outside this terminal's catalog": say so instead of "not found"
        return;
      }
      const hit = scan?.found ? catalog.find((v) => v.id === scan.variant_id) : null;
      if (hit) {
        if (addVariant(hit)) {
          setScanError("");
          clearIfStill(clean);
          toast.success(`تمت إضافة ${hit.productName}`);
        }
        return;
      }
    } catch {
      /* fall through to the local search */
    }
    const matches = searchCatalog(catalog, clean, 2).filter((v) => v.stock > 0);
    if (matches.length === 1) {
      if (addVariant(matches[0])) {
        setScanError("");
        clearIfStill(clean);
        toast.success(`تمت إضافة ${matches[0].productName}`);
      }
      return;
    }
    setScanError(matches.length > 1 ? `أكثر من صنف يطابق «${clean}» — اكتب الباركود أو الكود بالكامل` : `لا يوجد صنف متاح بـ ${clean}`);
  }

  function removeLine(line) {
    const index = lines.findIndex((l) => l.lineId === line.lineId);
    removedRef.current = { line, index };
    sale.remove(line.lineId);
    toast.info(`تم حذف ${line.name} من الفاتورة`, {
      id: UNDO_TOAST_ID,
      action: {
        label: "تراجع",
        onClick: () => {
          const removed = removedRef.current;
          if (!removed) return;
          removedRef.current = null;
          const v = catalog.find((c) => c.id === removed.line.variantId);
          const r = sale.restoreLine(removed.line, removed.index, v?.stock);
          toast.dismiss(UNDO_TOAST_ID);
          if (!r.ok) toast.warning(r.reason);
          else if (r.clamped) toast.warning(`المتاح من ${removed.line.name} أقل الآن، اتخفضت الكمية`);
        },
      },
    });
  }

  function applyLineDiscount(lineId, pct) {
    const value = Math.min(100, Math.max(0, Number(pct) || 0));
    sale.setLineDiscount(lineId, value);
  }

  function applyInvoiceDiscount(value) {
    const pct = Math.min(100, Math.max(0, Number(value) || 0));
    setInvoiceDiscountPct(pct);
  }

  function applyInvoiceAmount(value) {
    const amount = Math.max(0, Number(value) || 0);
    // A fixed discount can only take what is LEFT: the subtotal minus the lines' own discounts and
    // the invoice percentage. Capping at the bare subtotal let the three add up past the invoice,
    // which the server then refuses, so the sale got stuck instead of the box refusing the number.
    const pctDiscount = (subtotalNumber * (Number(invoiceDiscountPct) || 0)) / 100;
    const left = Math.max(0, +(subtotalNumber - lineDiscountsTotal - pctDiscount).toFixed(2));
    setInvoiceDiscountAmt(Math.min(amount, left));
  }

  function resetInvoice() {
    removedRef.current = null;
    toast.dismiss(UNDO_TOAST_ID);
    sale.clear();
    setInvoiceDiscountPct(0);
    setInvoiceDiscountAmt(0);
    setActiveLineId(null);
    setScanError("");
  }


  async function confirmHold(label) {
    setHolding(true);
    setHeldError(null);
    try {
      await sale.hold({ label });
      await refreshHeld();
      resetInvoice();
      setDialog(null);
      toast.success("تم تعليق الفاتورة");
    } catch (e) {
      setHeldError(e?.message || "تعذّر تعليق الفاتورة");
    } finally {
      setHolding(false);
    }
  }

  async function resumeHeld(h) {
    if (hasLines) {
      setHeldError("أكمل الفاتورة الحالية أو علّقها أو ألغها أولاً قبل استعادة فاتورة أخرى");
      return;
    }
    setHeldBusy(h.id);
    setHeldError(null);
    try {
      const r = await sale.restore(h.id);
      await refreshHeld();
      if (r.lines.length === 0) {
        setHeldError("لا يمكن استعادة هذه الفاتورة: كل أصنافها نافدة أو غير متاحة. بقيت معلقة كما هي.");
        return;
      }
      setDialog(null);
      if (r.releaseError) toast.warning(`تمت الاستعادة لكن بقيت نسخة معلقة: ${r.releaseError}`);
      for (const d of r.dropped) toast.warning(`${d.name}: ${d.reason === "out_of_stock" ? "نافد من المخزون فتم حذفه" : "غير متاح فتم حذفه"}`);
      for (const a of r.adjusted) toast.warning(`${a.name}: المتاح ${a.got} فقط (كان ${a.wanted})`);
      toast.success(`تمت استعادة «${h.label}»`);
    } catch (e) {
      setHeldError(e?.message || "تعذّرت الاستعادة");
    } finally {
      setHeldBusy(null);
    }
  }

  async function deleteHeld(h) {
    setHeldBusy(h.id);
    setHeldError(null);
    try {
      await posApi.releaseHeldCart(h.id);
    } catch (e) {
      if (e?.status !== 404) setHeldError(e?.message || "تعذّر الحذف");
    } finally {
      await refreshHeld();
      setHeldBusy(null);
    }
  }

  async function confirmSale() {
    try {
      const r = await sale.confirm({ cashier, customerName: displayCustomer === "عميل نقدي" ? "" : displayCustomer, customerId: pickedCustomer?.id });
      setDialog("receipt");
      toast.success(`تم إتمام البيع ${r.number} بمبلغ ${r.total.toFixed(2)} ج.م`);
      setInvoiceDiscountPct(0);
      setInvoiceDiscountAmt(0);
      setCustomerName("");
      setCustomerPhone("");
      setPickedCustomer(null);
    } catch {
      /* the confirm dialog shows sale.payError and stays open so the cashier can retry safely */
    }
  }

  useEffect(() => {
    function onKey(e) {
      if (e.key === "F2" && quoteReady) {
        e.preventDefault();
        setDialog("payment");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [quoteReady]);

  return (
    <div className="animate-fade-up flex h-full min-h-0 flex-col gap-2 overflow-hidden">
      <PosHeaderBar
        invoiceNo={lastReceipt ? `بعد ${lastReceipt.number}` : "جديدة"}
        cashier={cashier}
        shiftOpenedAt={session.opened_at}
        suspendedCount={heldQuery.data?.length ?? 0}
        onRestore={() => {
          setHeldError(null);
          refreshHeld();
          setDialog("held");
        }}
      />

      <PosInvoiceTable
        lines={lines}
        totals={finalTotals}
        barcode={barcode}
        onBarcodeChange={setBarcode}
        onBarcodeSubmit={submitBarcode}
        activeLineId={activeLineId}
        onActivate={setActiveLineId}
        onQty={sale.setQty}
        onQtyStep={sale.stepQty}
        onDiscount={applyLineDiscount}
        onRemove={removeLine}
      >
        <div className="flex flex-wrap items-center justify-center gap-x-8 gap-y-2 border-t border-border bg-muted/30 px-3 py-2">
          {scanError || sale.quote.error || catalogQuery.isError ? (
            <p className="flex w-full items-center gap-1.5 text-[11px] font-semibold text-rose-600" role="alert">
              <TriangleAlert className="h-3.5 w-3.5" />
              {scanError || sale.quote.error || "تعذّر تحميل الأصناف من الخادم"}
            </p>
          ) : null}

          <PosInvoiceDiscounts
            pct={invoiceDiscountPct}
            onPctChange={applyInvoiceDiscount}
            amount={invoiceDiscountAmt}
            onAmountChange={applyInvoiceAmount}
            disabled={!hasLines}
          />

          <PosCustomerFields
            name={customerName}
            onNameChange={setCustomerName}
            phone={customerPhone}
            onPhoneChange={setCustomerPhone}
            customer={pickedCustomer}
            onPick={(c) => {
              setPickedCustomer(c);
              if (c) setCustomerName("");
            }}
            results={customerSearch.data ?? []}
            searching={customerSearch.isFetching}
            required={requireCustomer}
          />
          {hasLines && needCustomer ? <p role="alert" className="max-w-[230px] text-[11px] font-bold text-destructive">{needCustomer}</p> : null}

          <PosInvoiceSummary subTotal={finalTotals.subTotal} discount={finalTotals.invoiceDiscount} total={finalTotals.total} />
        </div>
      </PosInvoiceTable>

      <PosActionsBar
        hasLines={quoteReady}
        hasLastReceipt={!!lastReceipt}
        hasNote={Boolean(sale.note)}
        payLabel="دفع وطباعة"
        onPay={() => setDialog("payment")}
        onSuspend={() => {
          setHeldError(null);
          setDialog("hold");
        }}
        onCancel={() => setDialog("cancel")}
        onNew={() => {
          resetInvoice();
          toast.info("تم بدء فاتورة جديدة");
        }}
        onReprint={() => {
          setReceipt(lastReceipt);
          setDialog("receipt");
        }}
        onNote={() => setDialog("note")}
      />

      <ConfirmSaleDialog
        open={dialog === "payment"}
        onOpenChange={(open) => setDialog(open ? "payment" : null)}
        total={sale.quote.total}
        customerName={displayCustomer}
        onConfirm={confirmSale}
        pending={sale.paying}
        error={sale.payError}
      />

      <NoteDialog
        open={dialog === "note"}
        onOpenChange={(open) => setDialog(open ? "note" : null)}
        value={sale.note}
        onSave={(text) => {
          sale.setNote(text);
          setDialog(null);
        }}
      />

      <HoldDialog open={dialog === "hold"} onOpenChange={(open) => setDialog(open ? "hold" : null)} defaultLabel={customerName.trim()} pending={holding} error={heldError} onConfirm={confirmHold} />

      <SuspendedDialog
        open={dialog === "held"}
        onOpenChange={(open) => setDialog(open ? "held" : null)}
        held={heldQuery.data ?? []}
        loading={heldQuery.isLoading}
        error={heldError || (heldQuery.isError ? "تعذّر تحميل الفواتير المعلقة" : null)}
        busyId={heldBusy}
        onResume={resumeHeld}
        onDelete={deleteHeld}
      />

      <ConfirmDialog
        open={dialog === "cancel"}
        onOpenChange={(open) => setDialog(open ? "cancel" : null)}
        title="إلغاء الفاتورة الحالية"
        description="سيتم حذف كل الأصناف والخصومات المسجلة في هذه الفاتورة. لا يمكن التراجع."
        confirmLabel="إلغاء الفاتورة"
        onConfirm={() => {
          resetInvoice();
          toast.info("تم إلغاء الفاتورة الحالية");
        }}
      />

      <ReceiptDialog
        open={dialog === "receipt"}
        onOpenChange={(open) => {
          if (!open) {
            setDialog(null);
            setReceipt(null);
          }
        }}
        receipt={receipt}
        onNewSale={() => resetInvoice()}
      />
    </div>
  );
}
