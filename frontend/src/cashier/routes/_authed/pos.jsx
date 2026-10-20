import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { TriangleAlert } from "lucide-react";
import PosHeaderBar from "@/cashier/components/pos/PosHeaderBar";
import PosCustomerFields from "@/cashier/components/pos/PosCustomerFields";
import PosInvoiceTable from "@/cashier/components/pos/PosInvoiceTable";
import PosActionsBar from "@/cashier/components/pos/PosActionsBar";
import PosInvoiceDiscounts from "@/cashier/components/pos/PosInvoiceDiscounts";
import PosInvoiceSummary from "@/cashier/components/pos/PosInvoiceSummary";
import NoteDialog from "@/cashier/components/pos/NoteDialog";
import PaymentDialog from "@/cashier/components/pos/PaymentDialog";
import SuspendedDialog from "@/cashier/components/pos/SuspendedDialog";
import ReceiptDialog from "@/cashier/components/pos/ReceiptDialog";
import ConfirmDialog from "@/cashier/components/ui-kit/ConfirmDialog";
import { removeSuspended, resumeSuspended, setLastReceipt, suspendInvoice, usePosState } from "@/cashier/lib/posStore";
import { useSalesSettings } from "@/cashier/lib/salesSettings";
import { allVariants, colorHex, customers, employees, findProductByBarcode, invoices, products, searchVariants } from "@/cashier/lib/mockData";
import { PAYMENT_METHODS } from "@/cashier/lib/format";


function invoiceNumber(seq) {
  return `INV-2026-${String(seq).padStart(4, "0")}`;
}

// مُعرّف ثابت لرسالة الحذف: كل حذف جديد يستبدل الرسالة السابقة، فيكون التراجع لأحدث حذف.
const UNDO_TOAST_ID = "pos-undo-remove";

function withTotals(line) {
  return { ...line, total: +(line.price * line.qty - line.discount).toFixed(2) };
}

// تجهيز بنود فاتورة معلقة لتكون قابلة للتعديل بنفس شكل بنود الفاتورة الحالية.
function resumeLines(items) {
  return items.map((it, index) => ({
    ...it,
    lineId: it.lineId ?? `${it.code ?? "line"}-${index}`,
    variantId: it.variantId ?? it.code ?? `line-${index}`,
    hex: it.hex ?? colorHex(it.color),
    stock: it.stock ?? allVariants.find((v) => v.sku === it.code || v.barcode === it.barcode)?.stock ?? 0,
  }));
}

// بناء بند فاتورة من صنف في المخزون (يُستخدم عند المسح وعند بنود العرض التجريبية).
function lineFromVariant(variant, lineId) {
  return {
    lineId,
    variantId: variant.id,
    code: variant.sku,
    barcode: variant.barcode,
    name: variant.productName,
    color: variant.color,
    hex: colorHex(variant.color),
    size: variant.size,
    stock: variant.stock,
    price: variant.sellPrice,
    qty: 1,
    discountPct: 0,
    discount: 0,
  };
}

// بنود تجريبية تظهر عند فتح الشاشة: ٣ أصناف حقيقية من المخزون.
const DEMO_LINES = [0, 4, 8].map((index, i) => {
  const variant = products[index].variants.find((v) => v.stock > 3) ?? products[index].variants[0];
  return lineFromVariant(variant, `demo-${i + 1}`);
});

export default function PosPage() {
  const posState = usePosState();
  const salesSettings = useSalesSettings();
  const [lines, setLines] = useState(() => DEMO_LINES.map((l) => ({ ...l })));
  const [barcode, setBarcode] = useState("");
  const [scanError, setScanError] = useState("");
  const [customerName, setCustomerName] = useState("");
  const [customerPhone, setCustomerPhone] = useState("");
  const [employee, setEmployee] = useState(employees[0].name);
  const [paid, setPaid] = useState(0);
  const [method, setMethod] = useState(salesSettings.defaultMethod);
  const [invoiceDiscountPct, setInvoiceDiscountPct] = useState(0);
  const [invoiceDiscountAmount, setInvoiceDiscountAmount] = useState(0);
  const [note, setNote] = useState("");
  const [activeLineId, setActiveLineId] = useState(null);
  const [dialog, setDialog] = useState(null); // payment | suspended | receipt | cancel | note
  const [receipt, setReceipt] = useState(null);
  const [sessionSales, setSessionSales] = useState([]); // فواتير أُتمّت في هذه الجلسة
  const [historyIndex, setHistoryIndex] = useState(-1); // الفاتورة المعروضة من السجل (-1 = لا شيء)
  const [seq, setSeq] = useState(invoices.length + 61);
  // آخر صنف محذوف: بياناته وموضعه الأصلي للاسترجاع عند الضغط على «تراجع».
  const removedRef = useRef(null);

  // سجل الفواتير القابل للتقليب: فواتير الجلسة أولاً ثم فواتير النظام (الأحدث أولاً).
  const invoiceHistory = [...sessionSales, ...invoices];

  const hasLines = lines.length > 0;
  // الزبون اختياري: بدون اسم تُسجَّل الفاتورة على عميل نقدي.
  const displayCustomer = customerName.trim() || "عميل نقدي";

  const totals = lines.reduce(
    (acc, l) => {
      const gross = l.price * l.qty;
      return {
        pieces: acc.pieces + l.qty,
        subTotal: acc.subTotal + gross,
        linesDiscount: acc.linesDiscount + l.discount,
        net: acc.net + gross - l.discount,
      };
    },
    { pieces: 0, subTotal: 0, linesDiscount: 0, net: 0 },
  );

  const pctDiscount = +((totals.net * (Number(invoiceDiscountPct) || 0)) / 100).toFixed(2);
  const invoiceDiscount = +Math.min(totals.net, pctDiscount + (Number(invoiceDiscountAmount) || 0)).toFixed(2);
  const finalTotals = { ...totals, pctDiscount, invoiceDiscount, total: +(totals.net - invoiceDiscount).toFixed(2) };

  function addVariant(variant) {
    const existing = lines.find((l) => l.variantId === variant.id);
    if (existing) {
      setLines((prev) => prev.map((l) => (l.variantId === variant.id ? { ...l, qty: l.qty + 1 } : l)));
      setActiveLineId(existing.lineId);
      return;
    }
    const lineId = `${variant.id}-${Date.now()}`;
    setLines((prev) => [...prev, lineFromVariant(variant, lineId)]);
    setActiveLineId(lineId);
  }

  function submitBarcode() {
    const clean = barcode.trim();
    if (!clean) return;

    const found = findProductByBarcode(clean);
    if (found) {
      if (found.variant.stock === 0) {
        setScanError(`${found.product.name} — ${found.variant.color} / ${found.variant.size} نافد من المخزون`);
        return;
      }
      addVariant(found.variant);
      setBarcode("");
      setScanError("");
      toast.success(`تمت إضافة ${found.product.name} — ${found.variant.color} / ${found.variant.size}`);
      return;
    }

    // بحث بالاسم أو الكود: لو فيه صنف واحد متاح نضيفه، وأكثر من صنف يستلزم الباركود بالكامل.
    const matches = searchVariants(clean, 2).filter((v) => v.stock > 0);
    if (matches.length === 1) {
      addVariant(matches[0]);
      setBarcode("");
      setScanError("");
      toast.success(`تمت إضافة ${matches[0].productName} — ${matches[0].color} / ${matches[0].size}`);
      return;
    }
    setScanError(matches.length > 1 ? `أكثر من صنف يطابق «${clean}» — اكتب الباركود بالكامل` : `لا يوجد صنف بالباركود ${clean}`);
  }

  // حذف صنف من الفاتورة، مع رسالة تتضمن زر «تراجع» لاسترجاعه كما كان.
  function removeLine(line) {
    const index = lines.findIndex((l) => l.lineId === line.lineId);
    removedRef.current = { line, index };
    setLines((prev) => prev.filter((l) => l.lineId !== line.lineId));
    toast.info(`تم حذف ${line.name} من الفاتورة`, {
      id: UNDO_TOAST_ID,
      action: { label: "تراجع", onClick: undoRemove },
    });
  }

  // استرجاع الصنف المحذوف بنفس بياناته (الكمية والخصم) وفي موضعه الأصلي.
  function undoRemove() {
    const removed = removedRef.current;
    if (!removed) return;
    removedRef.current = null;
    setLines((prev) => {
      if (prev.some((l) => l.lineId === removed.line.lineId)) return prev;
      const next = [...prev];
      next.splice(Math.min(Math.max(removed.index, 0), next.length), 0, removed.line);
      return next;
    });
    setActiveLineId(removed.line.lineId);
    toast.dismiss(UNDO_TOAST_ID);
    toast.success(`تم استرجاع ${removed.line.name} إلى الفاتورة`);
  }

  function updateLine(lineId, patch) {
    setLines((prev) =>
      prev.map((l) => {
        if (l.lineId !== lineId) return l;
        const next = { ...l, ...patch };
        next.discount = +((next.price * next.qty * next.discountPct) / 100).toFixed(2);
        return next;
      }),
    );
  }

  function setQty(lineId, value) {
    const qty = Math.max(1, Number(value) || 1);
    updateLine(lineId, { qty });
  }

  function stepQty(lineId, delta) {
    const line = lines.find((l) => l.lineId === lineId);
    if (!line) return;
    updateLine(lineId, { qty: Math.max(1, line.qty + delta) });
  }

  // الخصم محدود بما حُفظ في الإعدادات: أي نسبة أكبر تُصحَّح مع تنبيه.
  function applyLineDiscount(lineId, pct) {
    const limit = salesSettings.maxDiscountPct;
    const value = Math.max(0, Number(pct) || 0);
    if (value > limit) toast.warning(`أقصى خصم مسموح ${limit}% — عدّل الحد من الإعدادات`);
    updateLine(lineId, { discountPct: Math.min(limit, value) });
  }

  function applyInvoiceDiscount(value) {
    const limit = salesSettings.maxDiscountPct;
    const pct = Math.max(0, Number(value) || 0);
    if (pct > limit) toast.warning(`أقصى خصم مسموح على الفاتورة ${limit}%`);
    setInvoiceDiscountPct(Math.min(limit, pct));
  }

  // الخصم النقدي محدود بالمتبقي بعد خصم النسبة.
  function applyInvoiceDiscountAmount(value) {
    const limit = Math.max(0, +(totals.net - pctDiscount).toFixed(2));
    const amount = Math.max(0, Number(value) || 0);
    if (amount > limit) toast.warning(`أقصى خصم مسموح على الفاتورة ${limit.toFixed(2)} ج.م`);
    setInvoiceDiscountAmount(Math.min(limit, amount));
  }

  function resetInvoice({ keepSeq = false } = {}) {
    // لا تراجع عن حذف بعد بدء فاتورة جديدة (لئلا يعود صنف إلى فاتورة أخرى).
    removedRef.current = null;
    toast.dismiss(UNDO_TOAST_ID);
    setLines([]);
    setPaid(0);
    setInvoiceDiscountPct(0);
    setInvoiceDiscountAmount(0);
    setNote("");
    setActiveLineId(null);
    setMethod(salesSettings.defaultMethod);
    setHistoryIndex(-1);
    if (!keepSeq) setSeq((s) => s + 1);
  }

  function suspendCurrent() {
    if (!hasLines) return;
    const record = {
      id: `hold-${Date.now()}`,
      number: invoiceNumber(seq),
      customerName: displayCustomer,
      customerPhone: customerPhone.trim() || "—",
      cashier: employee,
      heldAt: new Date().toISOString(),
      note,
      discountPct: invoiceDiscountPct,
      discountAmount: invoiceDiscountAmount,
      items: lines.map(withTotals),
    };
    suspendInvoice(record);
    resetInvoice();
    toast.info(`تم تعليق الفاتورة ${record.number}`);
  }

  function buildReceipt(status = "paid") {
    return {
      number: invoiceNumber(seq),
      date: new Date().toISOString(),
      cashier: employee,
      customerName: displayCustomer,
      customerPhone: customerPhone.trim() || "—",
      items: lines.map(withTotals),
      pieces: finalTotals.pieces,
      subTotal: +finalTotals.subTotal.toFixed(2),
      lineDiscount: +finalTotals.linesDiscount.toFixed(2),
      invoiceDiscount: finalTotals.invoiceDiscount,
      discount: +(finalTotals.linesDiscount + finalTotals.invoiceDiscount).toFixed(2),
      total: finalTotals.total,
      paid: Number(paid) || 0,
      payment: method,
      paymentLabel: PAYMENT_METHODS[method].label,
      note,
      status,
    };
  }

  function confirmSale() {
    const record = buildReceipt("paid");
    setLastReceipt(record);
    setSessionSales((prev) => [record, ...prev]);
    setReceipt(record);
    resetInvoice();
    setHistoryIndex(0); // الفاتورة التي أُتمّت الآن هي الأحدث في السجل
    setDialog("receipt");
    toast.success(`تم إتمام البيع ${record.number} بمبلغ ${record.total.toFixed(2)} ج.م`);
  }

  // التقليب بين الفواتير: «السابق» (delta = 1) يفتح الأقدم، و«التالي» (delta = -1) يرجع للأحدث،
  // وفي الحالتين تُحمَّل الفاتورة في الجدول للتعديل بدلاً من الاكتفاء بمعاينتها.
  function browseInvoice(delta) {
    if (!invoiceHistory.length) return;
    const next = historyIndex < 0 ? 0 : Math.min(invoiceHistory.length - 1, Math.max(0, historyIndex + delta));
    setHistoryIndex(next);
    loadInvoice(invoiceHistory[next]);
  }

  function reprintLast() {
    if (!posState.lastReceipt) {
      toast.error("لا توجد فاتورة سابقة لإعادة طباعتها");
      return;
    }
    setReceipt(posState.lastReceipt);
    setDialog("receipt");
  }

  // تحميل بنود فاتورة في جدول الفاتورة لتعديلها (يُستخدم في الاستعادة والتنقل بين الفواتير).
  function applyInvoiceToGrid(record) {
    const resumed = resumeLines(record.items ?? []);
    setLines(resumed);
    setPaid(0);
    setInvoiceDiscountPct(record.discountPct ?? 0);
    setInvoiceDiscountAmount(record.invoiceDiscount ?? record.discountAmount ?? 0);
    setNote(record.note ?? "");
    setActiveLineId(resumed[resumed.length - 1]?.lineId ?? null);
    setCustomerName(record.customerName && record.customerName !== "عميل نقدي" ? record.customerName : "");
    setCustomerPhone(record.customerPhone && record.customerPhone !== "—" ? record.customerPhone : "");
  }

  // فتح فاتورة سابقة في جدول الكاشير لتعديل بنودها، مع إغلاق نافذة المعاينة.
  function loadInvoice(record) {
    if (!record) return;
    applyInvoiceToGrid(record);
    setReceipt(null);
    setDialog(null);
    toast.success(`تم تحميل الفاتورة ${record.number} في الجدول للتعديل`);
  }

  function resumeHold(record) {
    applyInvoiceToGrid(record);
    resumeSuspended(record.id);
    setDialog(null);
    toast.success(`تم استعادة الفاتورة ${record.number}`);
  }

  useEffect(() => {
    function onKey(e) {
      if (e.key === "F2" && hasLines) {
        e.preventDefault();
        setDialog("payment");
      }
      if (e.key === "F4" && hasLines) {
        e.preventDefault();
        suspendCurrent();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [hasLines, lines, seq, customerName, customerPhone, employee, invoiceDiscountPct, note]);

  // لو أُوقفت طريقة الدفع المختارة من الإعدادات، نرجع للطريقة الافتراضية.
  useEffect(() => {
    if (!salesSettings.enabledMethods.includes(method)) setMethod(salesSettings.defaultMethod);
  }, [salesSettings.enabledMethods, salesSettings.defaultMethod, method]);

  return (
    <div className="animate-fade-up flex h-[calc(100dvh-60px)] flex-col gap-2 overflow-hidden lg:h-[calc(100dvh-16px)]">
      <PosHeaderBar
        invoiceNo={invoiceNumber(seq)}
        employee={employee}
        employees={employees}
        onEmployeeChange={setEmployee}
        suspendedCount={posState.suspended.length}
        onRestore={() => setDialog("suspended")}
      />

      <PosInvoiceTable
        lines={lines}
        totals={finalTotals}
        barcode={barcode}
        onBarcodeChange={setBarcode}
        onBarcodeSubmit={submitBarcode}
        activeLineId={activeLineId}
        onActivate={setActiveLineId}
        onQty={setQty}
        onQtyStep={stepQty}
        onDiscount={applyLineDiscount}
        onRemove={removeLine}
        maxDiscount={salesSettings.maxDiscountPct}
      >
        <div className="flex flex-wrap items-center justify-center gap-x-8 gap-y-2 border-t border-border bg-muted/30 px-3 py-2">
          {scanError ? (
            <p className="flex w-full items-center gap-1.5 text-[11px] font-semibold text-rose-600">
              <TriangleAlert className="h-3.5 w-3.5" />
              {scanError}
            </p>
          ) : null}

          {/* الشريط كله في المنتصف: خصم الفاتورة، ثم بيانات الزبون، ثم المجموع في الطرف الشمال */}
          <PosInvoiceDiscounts
            pct={invoiceDiscountPct}
            onPctChange={applyInvoiceDiscount}
            amount={invoiceDiscountAmount}
            onAmountChange={applyInvoiceDiscountAmount}
            maxDiscount={salesSettings.maxDiscountPct}
            disabled={!hasLines}
          />

          <PosCustomerFields
            name={customerName}
            onNameChange={setCustomerName}
            phone={customerPhone}
            onPhoneChange={setCustomerPhone}
            customers={customers}
          />

          <PosInvoiceSummary
            subTotal={finalTotals.subTotal}
            discount={finalTotals.linesDiscount + finalTotals.invoiceDiscount}
            total={finalTotals.total}
          />
        </div>
      </PosInvoiceTable>

      <PosActionsBar
        hasLines={hasLines}
        hasLastReceipt={!!posState.lastReceipt}
        hasNote={!!note}
        onPay={() => setDialog("payment")}
        onSuspend={suspendCurrent}
        onCancel={() => setDialog("cancel")}
        onNew={() => {
          resetInvoice();
          toast.info("تم بدء فاتورة جديدة");
        }}
        onReprint={reprintLast}
        onNote={() => setDialog("note")}
        onPrev={() => browseInvoice(1)}
        onNext={() => browseInvoice(-1)}
        prevDisabled={!invoiceHistory.length}
        nextDisabled={historyIndex <= 0}
      />

      <PaymentDialog
        open={dialog === "payment"}
        onOpenChange={(open) => setDialog(open ? "payment" : null)}
        total={finalTotals.total}
        method={method}
        onMethodChange={setMethod}
        paid={paid}
        onPaidChange={setPaid}
        onConfirm={confirmSale}
        customerName={displayCustomer}
        enabledMethods={salesSettings.enabledMethods}
      />

      <SuspendedDialog
        open={dialog === "suspended"}
        onOpenChange={(open) => setDialog(open ? "suspended" : null)}
        suspended={posState.suspended}
        onResume={resumeHold}
        onDelete={(id) => {
          removeSuspended(id);
          toast.info("تم حذف الفاتورة المعلقة");
        }}
      />

      <NoteDialog
        open={dialog === "note"}
        onOpenChange={(open) => setDialog(open ? "note" : null)}
        note={note}
        onSave={(value) => {
          setNote(value);
          setDialog(null);
          toast.success(value ? "تم حفظ الملاحظة على الفاتورة" : "تم حذف الملاحظة");
        }}
      />

      <ConfirmDialog
        open={dialog === "cancel"}
        onOpenChange={(open) => setDialog(open ? "cancel" : null)}
        title="إلغاء الفاتورة الحالية"
        description="سيتم حذف كل الأصناف والخصومات والملاحظات المسجلة في هذه الفاتورة. لا يمكن التراجع."
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
        onEdit={() => loadInvoice(receipt)}
        onPrev={() => browseInvoice(1)}
        onNext={() => browseInvoice(-1)}
        prevDisabled={historyIndex < 0 || historyIndex >= invoiceHistory.length - 1}
        nextDisabled={historyIndex <= 0}
      />
    </div>
  );
}