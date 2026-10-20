import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import ExchangeHeaderBar from "@/cashier/components/exchanges/ExchangeHeaderBar";
import ExchangeInvoiceSearch from "@/cashier/components/exchanges/ExchangeInvoiceSearch";
import ExchangeOriginalTable from "@/cashier/components/exchanges/ExchangeOriginalTable";
import ExchangeOriginalTotalsBar from "@/cashier/components/exchanges/ExchangeOriginalTotalsBar";
import ExchangeNewItemsTable from "@/cashier/components/exchanges/ExchangeNewItemsTable";
import ExchangeSettlementBar from "@/cashier/components/exchanges/ExchangeSettlementBar";
import ExchangeActionsBar from "@/cashier/components/exchanges/ExchangeActionsBar";
import ExchangeReceiptDialog from "@/cashier/components/exchanges/ExchangeReceiptDialog";
import HeldExchangesDialog from "@/cashier/components/exchanges/HeldExchangesDialog";
import NoteDialog from "@/cashier/components/pos/NoteDialog";
import ConfirmDialog from "@/cashier/components/ui-kit/ConfirmDialog";
import { colorHex, employees, findProductByBarcode, invoices, searchVariants } from "@/cashier/lib/mockData";
import {
  applyStockMovement,
  completeExchange,
  holdExchange,
  nextExchangeNumber,
  priorExchangedQuantities,
  removeHeld,
  takeHeld,
  useExchangeState,
} from "@/cashier/lib/exchangeStore";
import { fmtMoney } from "@/cashier/lib/format";
import useFillRowCount from "@/cashier/hooks/use-fill-row-count";


// بناء بند بديل من متغير في المخزون.
function lineFromVariant(variant) {
  return {
    lineId: `${variant.id}-${Date.now()}`,
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
  };
}

// ملخّص نصي لأصناف العملية (يظهر في سجل الاستبدال).
function summarize(list) {
  if (!list.length) return "—";
  return list.length === 1 ? list[0] : `${list[0]} +${list.length - 1}`;
}

export default function ExchangePage() {
  const exchangeState = useExchangeState();
  const [employee, setEmployee] = useState(employees[0].name);
  const [invoiceTerm, setInvoiceTerm] = useState("");
  const [invoice, setInvoice] = useState(null);
  const [searchError, setSearchError] = useState("");
  const [originalLines, setOriginalLines] = useState([]);
  const [term, setTerm] = useState("");
  const [termError, setTermError] = useState("");
  const [newLines, setNewLines] = useState([]);
  const [note, setNote] = useState("");
  const [dialog, setDialog] = useState(null); // note | held | cancel | receipt
  const [receipt, setReceipt] = useState(null);
  const gridRef = useRef(null);
  const actionsRef = useRef(null);
  const fillRows = useFillRowCount({ areaRef: gridRef, bottomRef: actionsRef });

  // نتائج البحث: الفاتورة الأصلية.
  const searchKey = invoiceTerm.trim().toLowerCase();
  const digits = searchKey.replace(/\D/g, "");
  const invoiceMatches = (
    searchKey
      ? invoices.filter(
          (inv) =>
            inv.number.toLowerCase().includes(searchKey) ||
            inv.customerName.toLowerCase().includes(searchKey) ||
            (digits.length >= 4 && (inv.customerPhone ?? "").replace(/\D/g, "").includes(digits)) ||
            inv.items.some((it) => (it.barcode ?? "").includes(searchKey) || (it.code ?? "").toLowerCase().includes(searchKey)),
        )
      : invoices.slice(0, 5)
  ).slice(0, 6);

  // فواتير جاهزة للتجربة السريعة: أحدث الفواتير المكتملة التي بها أكثر من صنف.
  const quickPicks = invoices.filter((inv) => inv.status === "paid" && inv.items.length >= 2).slice(0, 3);

  // نتائج البحث: القطع البديلة (متغيرات متاحة في المخزون).
  const variantMatches = term.trim() ? searchVariants(term, 10).filter((v) => v.stock > 0) : [];

  // القطع المحوَّلة من الفاتورة الأصلية إلى جدول البدائل.
  const movedLines = originalLines.filter((l) => l.moveQty > 0);
  const exchangedTotals = {
    pieces: movedLines.reduce((sum, l) => sum + l.moveQty, 0),
    value: +movedLines.reduce((sum, l) => sum + l.unitNet * l.moveQty, 0).toFixed(2),
  };
  const newTotals = {
    pieces: newLines.reduce((sum, l) => sum + l.qty, 0),
    value: +newLines.reduce((sum, l) => sum + l.price * l.qty, 0).toFixed(2),
  };
  const difference = +(newTotals.value - exchangedTotals.value).toFixed(2);

  const hasDraft = !!invoice || newLines.length > 0 || !!note;
  const canComplete = !!invoice && exchangedTotals.pieces > 0 && newLines.length > 0;
  const canPrint = (!!invoice && (exchangedTotals.pieces > 0 || newLines.length > 0)) || !!exchangeState.lastOperation;

  // بنود الفاتورة الأصلية: الكمية المتاحة للاستبدال = المباع ناقص ما سبق استبداله في عمليات معتمدة،
  // وسعر الوحدة من سعر البيع الفعلي في الفاتورة (بعد الخصم)، والبنود للعرض فقط.
  function buildOriginalLines(inv) {
    const exchanged = priorExchangedQuantities(inv.id);
    return inv.items.map((it, index) => {
      const unitNet = +((it.total ?? it.price * it.qty) / it.qty).toFixed(2);
      return {
        ...it,
        key: `${it.name}|${it.color}|${it.size}|${index}`,
        hex: colorHex(it.color),
        unitNet,
        maxQty: Math.max(0, it.qty - (exchanged[`${it.name}|${it.color}|${it.size}`] || 0)),
        alreadyExchanged: exchanged[`${it.name}|${it.color}|${it.size}`] || 0,
        moveQty: 0,
      };
    });
  }

  // تحديث المتاح لبنود عملية معلقة عند استعادتها دون فقد الكميات المحوَّلة.
  function refreshAvailability(inv, lines) {
    if (!inv) return lines;
    const fresh = buildOriginalLines(inv);
    return lines.map((line) => {
      const current = fresh.find((f) => f.key === line.key);
      if (!current) return line;
      const moveQty = Math.min(Math.max(0, line.moveQty || 0), current.maxQty);
      return { ...line, alreadyExchanged: current.alreadyExchanged, maxQty: current.maxQty, moveQty };
    });
  }

  // تحميل الفاتورة الأصلية: يظهر المتاح محدّثًا بعد كل عملية استبدال.
  function selectInvoice(inv) {
    const lines = buildOriginalLines(inv);

    setInvoice({ ...inv, lines });
    setOriginalLines(lines);
    setNewLines([]);
    setNote("");
    setInvoiceTerm(inv.number);
    setSearchError("");
    toast.success(`تم تحميل الفاتورة ${inv.number} — ${inv.items.length} صنف`);

    const used = lines.filter((r) => r.alreadyExchanged > 0);
    if (used.length) {
      toast.info(`${used.length} صنف سبق استبداله — المتاح للاستبدال محدّث.`);
    }
  }

  function submitSearch() {
    const clean = invoiceTerm.trim();
    if (!clean) {
      setSearchError("اكتب رقم الفاتورة أو هاتف العميل أولًا");
      return;
    }
    const key = clean.toLowerCase();
    const keyDigits = key.replace(/\D/g, "");
    const exact = invoices.find(
      (inv) =>
        inv.number.toLowerCase() === key ||
        inv.id.toLowerCase() === key ||
        (keyDigits.length >= 6 && (inv.customerPhone ?? "").replace(/\D/g, "") === keyDigits) ||
        inv.items.some((it) => (it.barcode ?? "") === key),
    );
    if (exact) {
      selectInvoice(exact);
      return;
    }
    if (invoiceMatches.length === 1) {
      selectInvoice(invoiceMatches[0]);
      return;
    }
    setSearchError(invoiceMatches.length ? `أكثر من فاتورة مطابقة «${clean}» — اختر من القائمة` : `لا توجد فاتورة مطابقة لـ «${clean}»`);
  }

  // نقل قطعة من الفاتورة الأصلية إلى جدول البدائل: تبقى باقي القطع في جدول الفاتورة.
  function startMove(key) {
    setOriginalLines((prev) => prev.map((l) => (l.key === key && l.maxQty > 0 ? { ...l, moveQty: 1 } : l)));
  }

  function cancelMove(key) {
    setOriginalLines((prev) => prev.map((l) => (l.key === key ? { ...l, moveQty: 0 } : l)));
  }

  function setMoveQty(key, value) {
    setOriginalLines((prev) =>
      prev.map((l) => (l.key === key ? { ...l, moveQty: Math.min(l.maxQty, Math.max(1, Number(value) || 1)) } : l)),
    );
  }

  function stepMoveQty(key, delta) {
    setOriginalLines((prev) =>
      prev.map((l) => (l.key === key ? { ...l, moveQty: Math.min(l.maxQty, Math.max(1, l.moveQty + delta)) } : l)),
    );
  }

  // إضافة قطعة بديلة (مع مراعاة الرصيد المتاح ومنع التكرار).
  function addVariant(variant) {
    if (variant.stock === 0) {
      toast.error(`${variant.productName} — ${variant.color} / ${variant.size} نافد من المخزون`);
      return;
    }
    const existing = newLines.find((l) => l.code === variant.sku && l.color === variant.color && l.size === variant.size);
    if (existing) {
      if (existing.qty >= variant.stock) {
        toast.warning(`المتاح من ${variant.productName} ${variant.stock} قطعة فقط`);
        return;
      }
      setNewLines((prev) => prev.map((l) => (l.lineId === existing.lineId ? { ...l, qty: l.qty + 1 } : l)));
    } else {
      setNewLines((prev) => [...prev, lineFromVariant(variant)]);
    }
    setTerm("");
    setTermError("");
    toast.success(`تمت إضافة ${variant.productName} — ${variant.color} / ${variant.size} كبديل`);
  }

  function submitTerm() {
    const clean = term.trim();
    if (!clean) return;

    const found = findProductByBarcode(clean);
    if (found) {
      addVariant({ ...found.variant, productName: found.product.name });
      return;
    }

    if (variantMatches.length === 1) {
      addVariant(variantMatches[0]);
      return;
    }
    setTermError(variantMatches.length ? `أكثر من صنف يطابق «${clean}» — اختر من النتائج` : `لا يوجد صنف متاح بالباركود أو الاسم «${clean}»`);
  }

  function setNewLineQty(lineId, value) {
    setNewLines((prev) =>
      prev.map((l) => (l.lineId === lineId ? { ...l, qty: Math.max(1, Math.min(Math.max(l.stock, 1), Number(value) || 1)) } : l)),
    );
  }

  function stepNewLineQty(lineId, delta) {
    setNewLines((prev) =>
      prev.map((l) => {
        if (l.lineId !== lineId) return l;
        const next = Math.max(1, l.qty + delta);
        if (delta > 0 && l.stock > 0 && next > l.stock) {
          toast.warning(`المتاح من ${l.name} ${l.stock} قطعة فقط`);
          return l;
        }
        return { ...l, qty: next };
      }),
    );
  }

  function removeNewLine(line) {
    setNewLines((prev) => prev.filter((l) => l.lineId !== line.lineId));
    toast.info(`تم حذف ${line.name} من القطع البديلة`);
  }

  function resetDraft() {
    setInvoice(null);
    setOriginalLines([]);
    setNewLines([]);
    setNote("");
    setTerm("");
    setTermError("");
    setInvoiceTerm("");
    setSearchError("");
  }

  // بناء مستند العملية (مسودة للمعاينة أو معتمد بعد الإتمام).
  function buildRecord(status) {
    const exchanged = movedLines.map((l) => ({
      name: l.name,
      code: l.code,
      barcode: l.barcode,
      color: l.color,
      size: l.size,
      qty: l.moveQty,
      unitNet: l.unitNet,
      total: +(l.unitNet * l.moveQty).toFixed(2),
    }));
    const replacements = newLines.map((l) => ({
      name: l.name,
      code: l.code,
      barcode: l.barcode,
      color: l.color,
      size: l.size,
      qty: l.qty,
      price: l.price,
      total: +(l.price * l.qty).toFixed(2),
    }));

    return {
      id: `exc-${Date.now()}`,
      number: nextExchangeNumber(),
      date: new Date().toISOString(),
      employee,
      customer: invoice?.customerName ?? "عميل نقدي",
      customerPhone: invoice?.customerPhone ?? "—",
      invoiceId: invoice?.id ?? null,
      invoiceNumber: invoice?.number ?? "—",
      returns: exchanged,
      replacements,
      returnedValue: exchangedTotals.value,
      newValue: newTotals.value,
      difference,
      settlement: difference > 0 ? "collected" : difference < 0 ? "refunded" : "even",
      returnedItem: summarize(exchanged.map((l) => `${l.name} — ${l.color} / ${l.size}`)),
      newItem: summarize(replacements.map((l) => `${l.name} — ${l.color} / ${l.size}`)),
      note,
      status,
    };
  }

  function differenceLabel() {
    if (difference === 0) return "بدون فرق";
    return difference > 0 ? `تحصيل فرق ${fmtMoney(difference)}` : `رد فرق ${fmtMoney(Math.abs(difference))}`;
  }

  // إتمام الاستبدال: تحديث المخزون، تسجيل الفرق، وإظهار المستند للطباعة.
  function confirmExchange() {
    const record = buildRecord("completed");
    applyStockMovement(movedLines.map((l) => ({ ...l, qty: l.moveQty })), newLines);
    completeExchange(record);
    setReceipt(record);
    resetDraft();
    setDialog("receipt");
    toast.success(`تم إتمام الاستبدال ${record.number} — ${differenceLabel()}`);
  }

  // تعليق العملية لاستكمالها لاحقًا (تُحفظ محليًا بدون أي تأثير على المخزون).
  function holdCurrent() {
    const record = {
      id: `hold-${Date.now()}`,
      number: nextExchangeNumber(),
      heldAt: new Date().toISOString(),
      employee,
      customer: invoice?.customerName ?? "عميل نقدي",
      invoice,
      returnLines: originalLines,
      newLines,
      note,
      returnedValue: exchangedTotals.value,
      newValue: newTotals.value,
    };
    holdExchange(record);
    resetDraft();
    toast.info(`تم تعليق العملية ${record.number}`);
  }

  function restoreHeld(record) {
    const taken = takeHeld(record.id);
    if (!taken) return;
    const restoredInvoice = taken.invoice ?? null;
    setInvoice(restoredInvoice);
    setOriginalLines(refreshAvailability(restoredInvoice, taken.returnLines ?? []));
    setNewLines(taken.newLines ?? []);
    setNote(taken.note ?? "");
    setEmployee(taken.employee ?? employees[0].name);
    setInvoiceTerm(taken.invoice?.number ?? "");
    setDialog(null);
    toast.success(`تم استعادة العملية ${taken.number}`);
  }

  function openReceipt() {
    if (invoice && (exchangedTotals.pieces > 0 || newLines.length > 0)) {
      setReceipt(buildRecord("draft"));
      setDialog("receipt");
      return;
    }
    if (exchangeState.lastOperation) {
      setReceipt(exchangeState.lastOperation);
      setDialog("receipt");
      return;
    }
    toast.error("لا توجد عملية استبدال لطباعتها");
  }

  useEffect(() => {
    function onKey(e) {
      if (e.key === "F2" && canComplete) {
        e.preventDefault();
        confirmExchange();
      }
      if (e.key === "F4" && hasDraft) {
        e.preventDefault();
        holdCurrent();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className="animate-fade-up flex flex-col gap-2 pb-2">
      <ExchangeHeaderBar
        number={nextExchangeNumber()}
        employee={employee}
        employees={employees}
        onEmployeeChange={setEmployee}
        heldCount={exchangeState.held.length}
        onRestore={() => setDialog("held")}
      />

      <ExchangeInvoiceSearch
        term={invoiceTerm}
        onTermChange={(value) => {
          setInvoiceTerm(value);
          setSearchError("");
        }}
        onSubmit={submitSearch}
        error={searchError}
        invoice={invoice}
        matches={invoiceMatches}
        quickPicks={quickPicks}
        onPick={selectInvoice}
        onClear={() => {
          setInvoice(null);
          setOriginalLines([]);
          setNewLines([]);
          setInvoiceTerm("");
          setSearchError("");
        }}
      />

      <div ref={gridRef} className="grid gap-2 2xl:grid-cols-2">
        <div className="flex min-h-0 flex-col gap-1.5">
          <ExchangeOriginalTable
            invoice={invoice}
            lines={originalLines}
            onStart={startMove}
            onQty={setMoveQty}
            onQtyStep={stepMoveQty}
            onCancel={cancelMove}
            totals={exchangedTotals}
            minRows={fillRows}
          />

          <ExchangeOriginalTotalsBar totals={exchangedTotals} />
        </div>

        <div className="flex min-h-0 flex-col gap-1.5">
          <ExchangeNewItemsTable
            lines={newLines}
            term={term}
            onTermChange={(value) => {
              setTerm(value);
              setTermError("");
            }}
            onSubmit={submitTerm}
            onQty={setNewLineQty}
            onQtyStep={stepNewLineQty}
            onRemove={removeNewLine}
            matches={variantMatches}
            onPick={addVariant}
            error={termError}
            totals={newTotals}
            movedPieces={exchangedTotals.pieces}
            minRows={fillRows}
          />

          <ExchangeSettlementBar exchangedValue={exchangedTotals.value} newValue={newTotals.value} difference={difference} />
        </div>
      </div>

      <div ref={actionsRef}>
        <ExchangeActionsBar
        canComplete={canComplete}
        canPrint={canPrint}
        hasNote={!!note}
        hasDraft={hasDraft}
        onComplete={confirmExchange}
        onPrint={openReceipt}
        onNote={() => setDialog("note")}
        onHold={holdCurrent}
        onCancel={() => setDialog("cancel")}
        />
      </div>

      <NoteDialog
        open={dialog === "note"}
        onOpenChange={(open) => setDialog(open ? "note" : null)}
        note={note}
        title="ملاحظة على عملية الاستبدال"
        description="اكتب أي ملاحظة تخص العملية أو العميل، وستُطبع مع مستند الاستبدال."
        placeholder="مثال: العميل سيستبدل المقاس مرة أخرى خلال أسبوع"
        onSave={(value) => {
          setNote(value);
          setDialog(null);
          toast.success(value ? "تم حفظ الملاحظة على العملية" : "تم حذف الملاحظة");
        }}
      />

      <HeldExchangesDialog
        open={dialog === "held"}
        onOpenChange={(open) => setDialog(open ? "held" : null)}
        held={exchangeState.held}
        onResume={restoreHeld}
        onDelete={(id) => {
          removeHeld(id);
          toast.info("تم حذف العملية المعلقة");
        }}
      />

      <ConfirmDialog
        open={dialog === "cancel"}
        onOpenChange={(open) => setDialog(open ? "cancel" : null)}
        title="إلغاء عملية الاستبدال"
        description="سيتم حذف الفاتورة المختارة والبنود والملاحظات المسجلة في هذه العملية، دون أي تأثير على المخزون أو تسجيل مرتجع."
        confirmLabel="إلغاء العملية"
        onConfirm={() => {
          resetDraft();
          toast.info("تم إلغاء عملية الاستبدال");
        }}
      />

      <ExchangeReceiptDialog
        open={dialog === "receipt"}
        onOpenChange={(open) => {
          if (!open) {
            setDialog(null);
            setReceipt(null);
          }
        }}
        operation={receipt}
        onNewOperation={resetDraft}
      />
    </div>
  );
}