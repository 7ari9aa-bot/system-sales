import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Link, useSearchParams } from "react-router-dom";
import { TriangleAlert } from "lucide-react";
import PosHeaderBar from "@/cashier/components/pos/PosHeaderBar";
import PosCustomerFields from "@/cashier/components/pos/PosCustomerFields";
import PosInvoiceTable from "@/cashier/components/pos/PosInvoiceTable";
import PosActionsBar from "@/cashier/components/pos/PosActionsBar";
import PosInvoiceDiscounts from "@/cashier/components/pos/PosInvoiceDiscounts";
import PosInvoiceSummary from "@/cashier/components/pos/PosInvoiceSummary";
import PaymentDialog from "@/cashier/components/pos/PaymentDialog";
import ReceiptDialog from "@/cashier/components/pos/ReceiptDialog";
import SuspendedDialog from "@/cashier/components/pos/SuspendedDialog";
import HoldDialog from "@/cashier/components/pos/HoldDialog";
import ConfirmDialog from "@/cashier/components/ui-kit/ConfirmDialog";
import { Button } from "@/cashier/components/ui/button";
import { CATALOG_KEY, HELD_KEY, SESSION_CATALOG_KEY, fetchSessionCatalog, useCustomerSearch, useHeldCarts, usePosSale, useSessionCatalog, useShiftProfile } from "@/cashier/api/usePosSale";
import { customerBlock } from "@/cashier/api/customerRule";
import { useShiftState } from "@/cashier/api/useShifts";
import { searchCatalog } from "@/cashier/api/catalogAdapter";
import { posApi } from "@/cashier/api/posApi";
import { approvalFailure, approvalReason, needsApproval } from "@/cashier/api/approval";
import ManagerApprovalDialog from "@/cashier/components/shifts/ManagerApprovalDialog";
import { ceilingPct } from "@/cashier/lib/discountCeiling";
import { useAuth } from "@/lib/AuthContext";

// Only methods the backend accepts; the profile's own list narrows this further once loaded.

// مُعرّف ثابت لرسالة الحذف: كل حذف جديد يستبدل الرسالة السابقة، فيكون التراجع لأحدث حذف.
const UNDO_TOAST_ID = "pos-undo-remove";

function NoShift({ state }) {
  const text =
    state.status === "needs_setup"
      ? "لم يتم تجهيز الكاشير بعد. افتح أول وردية من شاشة الورديات لتجهيزه."
      : state.status === "forbidden"
        ? "ليست لديك صلاحية استخدام الكاشير."
        : state.status === "error"
          ? state.message || "تعذّر تحميل حالة الوردية."
          : "لا توجد وردية مفتوحة. افتح وردية لتبدأ البيع.";
  return (
    <div className="animate-fade-up mx-auto mt-16 flex max-w-md flex-col items-center gap-3 rounded-2xl border border-border bg-card p-8 text-center">
      <TriangleAlert className="h-7 w-7 text-amber-600" aria-hidden="true" />
      <p className="text-sm font-semibold" role="status">{text}</p>
      <Button asChild>
        <Link to="/cashier/shifts">الذهاب إلى الورديات</Link>
      </Button>
    </div>
  );
}

export default function PosPage() {
  const { user } = useAuth?.() ?? {};
  const shift = useShiftState({ canConfigure: false });
  if (shift.isLoading) return <p className="p-8 text-center text-sm text-muted-foreground" role="status">جارٍ التحميل…</p>;
  if (shift.data?.status !== "open") return <NoShift state={shift.data ?? { status: "error", message: shift.error?.message }} />;
  return <PosScreen user={user} session={shift.data.session} />;
}

function PosScreen({ user, session }) {
  const qc = useQueryClient();
  const catalogQuery = useSessionCatalog(session.id); // this till's items, price and warehouse stock
  const catalog = useMemo(() => catalogQuery.data ?? [], [catalogQuery.data]);
  const [receipt, setReceipt] = useState(null);
  const [lastReceipt, setLastReceipt] = useState(null);
  const sale = usePosSale({
    sessionId: session.id,
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
  const maxDiscountPct = ceilingPct(profile.data); // the number the server enforces; above it a manager PIN is asked
  const customerSearch = useCustomerSearch(pickedCustomer ? "" : customerName);
  const needCustomer = customerBlock({ requireCustomer, customerId: pickedCustomer?.id });
  const [activeLineId, setActiveLineId] = useState(null);
  const [invoiceDiscountPct, setInvoiceDiscountPct] = useState(0);
  const [invoiceDiscountAmt, setInvoiceDiscountAmt] = useState(0);
  // The shift screen links here with ?held=1 to review parked invoices before closing: open that list once.
  const [searchParams, setSearchParams] = useSearchParams();
  const [dialog, setDialog] = useState(() => (searchParams.get("held") === "1" ? "held" : null)); // payment | receipt | cancel | held
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
  useEffect(() => {
    const fromPct = (subtotalNumber * (Number(invoiceDiscountPct) || 0)) / 100;
    const amount = +(fromPct + (Number(invoiceDiscountAmt) || 0)).toFixed(2);
    sale.setInvoiceDiscount(amount > 0 ? String(amount) : "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invoiceDiscountPct, invoiceDiscountAmt, subtotalNumber]);

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

  async function submitBarcode() {
    const clean = barcode.trim();
    if (!clean) return;
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
          setBarcode("");
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
        setBarcode("");
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

  // The server owns the ceiling. A discount above it is NOT blocked here: it is allowed up to 100% and the cashier is
  // told the payment will ask for a manager's PIN (that approval flow is what lets a manager grant a bigger discount).
  function warnIfOverCeiling(pct, what) {
    if (pct > maxDiscountPct) toast.info(`${what} ${pct}% أعلى من حد الكاشير ${maxDiscountPct}%: سيُطلب رقم المدير السري عند الدفع`, { id: "discount-over-ceiling" });
  }

  function applyLineDiscount(lineId, pct) {
    const value = Math.min(100, Math.max(0, Number(pct) || 0));
    warnIfOverCeiling(value, "خصم الصنف");
    sale.setLineDiscount(lineId, value);
  }

  function applyInvoiceDiscount(value) {
    const pct = Math.min(100, Math.max(0, Number(value) || 0));
    warnIfOverCeiling(pct, "خصم الفاتورة");
    setInvoiceDiscountPct(pct);
  }

  function applyInvoiceAmount(value) {
    const amount = Math.max(0, Number(value) || 0);
    // a fixed discount can never exceed the subtotal (the total must not go negative)
    setInvoiceDiscountAmt(Math.min(amount, subtotalNumber));
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

  // A discount above the till's limit waits here for a manager; the tenders are kept so the retry is the same sale.
  const [approval, setApproval] = useState(null);

  async function confirmSale(tenders, managerOk) {
    try {
      const r = await sale.pay({ tenders, approval: managerOk, cashier, customerName: displayCustomer === "عميل نقدي" ? "" : displayCustomer, customerId: pickedCustomer?.id });
      setApproval(null);
      setDialog("receipt");
      toast.success(`تم إتمام البيع ${r.number} بمبلغ ${r.total.toFixed(2)} ج.م`);
      setInvoiceDiscountPct(0);
      setInvoiceDiscountAmt(0);
      setCustomerName("");
      setCustomerPhone("");
      setPickedCustomer(null);
    } catch (e) {
      if (needsApproval(e) && !managerOk) {
        setDialog(null); // the payment box gives way to the manager box
        setApproval({ tenders, reason: approvalReason(e), error: null });
      } else if (managerOk) {
        setApproval((a) => ({ ...(a ?? { tenders }), error: approvalFailure(e) }));
      }
      /* otherwise the payment dialog shows sale.payError and stays open so the cashier can retry safely */
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
    <div className="animate-fade-up flex h-[calc(100dvh-60px)] flex-col gap-2 overflow-hidden lg:h-[calc(100dvh-16px)]">
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
        hasNote={false}
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
        onNote={() => toast.info("الملاحظات على الفاتورة غير متاحة بعد")}
      />

      <ManagerApprovalDialog
        open={Boolean(approval)}
        reason={approval?.reason}
        pending={sale.paying}
        error={approval?.error}
        onCancel={() => setApproval(null)}
        onApprove={(ok) => confirmSale(approval.tenders, ok)}
      />

      <PaymentDialog
        open={dialog === "payment"}
        onOpenChange={(open) => setDialog(open ? "payment" : null)}
        total={sale.quote.total}
        customerName={displayCustomer}
        onConfirm={confirmSale}
        pending={sale.paying}
        error={sale.payError}
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
