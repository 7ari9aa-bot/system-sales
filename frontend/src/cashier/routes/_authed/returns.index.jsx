import { useNavigate, useSearchParams } from "react-router-dom";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import ExchangeInvoiceSearch from "@/cashier/components/exchanges/ExchangeInvoiceSearch";
import ConfirmDialog from "@/cashier/components/ui-kit/ConfirmDialog";
import ReturnActionsBar from "@/cashier/components/returns/ReturnActionsBar";
import ReturnHeaderBar from "@/cashier/components/returns/ReturnHeaderBar";
import ReturnItemsTable from "@/cashier/components/returns/ReturnItemsTable";
import ReturnOriginalTable from "@/cashier/components/returns/ReturnOriginalTable";
import ReturnSettlementBar from "@/cashier/components/returns/ReturnSettlementBar";
import ReturnTotalsBar from "@/cashier/components/returns/ReturnTotalsBar";
import useFillRowCount from "@/cashier/hooks/use-fill-row-count";
import { fmtMoney } from "@/cashier/lib/format";
import { colorHex, employees, invoices } from "@/cashier/lib/mockData";
import { completeReturn, nextReturnNumber } from "@/cashier/lib/returnsStore";
import { applyStockMovement } from "@/cashier/lib/stockMovement";


// بنود الفاتورة الأصلية: المتاح للاسترجاع = المباع ناقص ما سبق استرجاعه، والسعر الصافي بعد الخصم.
function buildLines(invoice) {
  const returned = {};
  invoice.returns.forEach((r) =>
    r.items.forEach((ri) => {
      const key = `${ri.name}|${ri.color}|${ri.size}`;
      returned[key] = (returned[key] || 0) + ri.qty;
    }),
  );

  return invoice.items.map((it, index) => {
    const alreadyReturned = returned[`${it.name}|${it.color}|${it.size}`] || 0;
    return {
      ...it,
      key: `${it.name}|${it.color}|${it.size}|${index}`,
      hex: colorHex(it.color),
      unitNet: +((it.total ?? it.price * it.qty) / it.qty).toFixed(2),
      alreadyReturned,
      maxQty: Math.max(0, it.qty - alreadyReturned),
      returnQty: 0,
    };
  });
}

export default function NewReturnPage() {
  const navigate = useNavigate();
  const { invoice: invoiceParam } = Object.fromEntries(useSearchParams()[0]);
  const [employee, setEmployee] = useState(employees[0].name);
  const [invoice, setInvoice] = useState(null);
  const [lines, setLines] = useState([]);
  const [term, setTerm] = useState("");
  const [error, setError] = useState("");
  const [reason, setReason] = useState("");
  const [refundMethod, setRefundMethod] = useState("cash");
  const [cancelOpen, setCancelOpen] = useState(false);
  const gridRef = useRef(null);
  const actionsRef = useRef(null);
  const fillRows = useFillRowCount({ areaRef: gridRef, bottomRef: actionsRef });

  // فواتير جاهزة للتجربة السريعة.
  const quickPicks = invoices.filter((inv) => inv.status === "paid" && inv.items.length >= 2).slice(0, 3);

  const searchKey = term.trim().toLowerCase();
  const digits = searchKey.replace(/\D/g, "");
  const matches = (searchKey
    ? invoices.filter(
        (inv) =>
          inv.number.toLowerCase().includes(searchKey) ||
          inv.customerName.toLowerCase().includes(searchKey) ||
          (digits.length >= 4 && (inv.customerPhone ?? "").replace(/\D/g, "").includes(digits)) ||
          inv.items.some((it) => (it.barcode ?? "").includes(searchKey)),
      )
    : invoices.slice(0, 5)
  ).slice(0, 6);

  const pickedLines = lines.filter((l) => l.returnQty > 0);
  const totals = {
    pieces: pickedLines.reduce((sum, l) => sum + l.returnQty, 0),
    value: +pickedLines.reduce((sum, l) => sum + l.unitNet * l.returnQty, 0).toFixed(2),
  };
  const hasDraft = !!invoice || pickedLines.length > 0;
  const canComplete = !!invoice && pickedLines.length > 0 && !!reason;

  function selectInvoice(inv) {
    const fresh = buildLines(inv);
    setInvoice(inv);
    setLines(fresh);
    setTerm(inv.number);
    setReason("");
    setError("");
    toast.success(`تم تحميل الفاتورة ${inv.number} — ${inv.items.length} صنف`);

    const used = fresh.filter((l) => l.alreadyReturned > 0);
    if (used.length) toast.info(`${used.length} صنف سبق استرجاعه — المتاح محدّث.`);
  }

  function submitSearch() {
    const clean = term.trim();
    if (!clean) {
      setError("اكتب رقم الفاتورة أو هاتف العميل أولًا");
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
    if (matches.length === 1) {
      selectInvoice(matches[0]);
      return;
    }
    setError(matches.length ? `أكثر من فاتورة مطابقة «${clean}» — اختر من القائمة` : `لا توجد فاتورة مطابقة لـ «${clean}»`);
  }

  // نقل قطعة من الفاتورة الأصلية إلى جدول المرتجع.
  function startReturn(key) {
    setLines((prev) => prev.map((l) => (l.key === key && l.maxQty > 0 ? { ...l, returnQty: 1 } : l)));
  }

  function cancelReturn(key) {
    setLines((prev) => prev.map((l) => (l.key === key ? { ...l, returnQty: 0 } : l)));
  }

  function setReturnQty(key, value) {
    setLines((prev) => prev.map((l) => (l.key === key ? { ...l, returnQty: Math.min(l.maxQty, Math.max(1, Number(value) || 1)) } : l)));
  }

  function stepReturnQty(key, delta) {
    setLines((prev) => prev.map((l) => (l.key === key ? { ...l, returnQty: Math.min(l.maxQty, Math.max(1, l.returnQty + delta)) } : l)));
  }

  function resetDraft() {
    setInvoice(null);
    setLines([]);
    setTerm("");
    setError("");
    setReason("");
  }

  // اعتماد المرتجع: تسجيله في السجل، إرجاع الكميات للمخزون، وتحديث الفاتورة الأصلية.
  function confirmReturn() {
    const record = {
      id: `ret-${Date.now()}`,
      number: nextReturnNumber(),
      date: new Date().toISOString(),
      invoiceId: invoice.id,
      invoiceNumber: invoice.number,
      customer: invoice.customerName,
      productName: pickedLines.length > 1 ? `${pickedLines[0].name} +${pickedLines.length - 1}` : pickedLines[0].name,
      variant: `${pickedLines[0].color} / ${pickedLines[0].size}`,
      qty: totals.pieces,
      amount: totals.value,
      refundMethod,
      reason,
      employee,
      status: "completed",
      items: pickedLines.map((l) => ({
        name: l.name,
        code: l.code,
        barcode: l.barcode,
        color: l.color,
        size: l.size,
        qty: l.returnQty,
        unitNet: l.unitNet,
        total: +(l.unitNet * l.returnQty).toFixed(2),
      })),
    };

    // الكميات المرتجعة تعود لمخزون نفس المتغير (لون / مقاس).
    applyStockMovement(
      pickedLines.map((l) => ({ code: l.code, barcode: l.barcode, qty: l.returnQty })),
      [],
    );

    // تُسجَّل العملية على الفاتورة الأصلية: تحدّث المتاح للاسترجاع وتظهر في تفاصيل الفاتورة.
    const source = invoices.find((i) => i.id === invoice.id);
    source?.returns.push({
      id: record.id,
      date: record.date,
      type: "return",
      amount: record.amount,
      items: record.items.map((i) => ({ name: i.name, color: i.color, size: i.size, qty: i.qty })),
      reason,
      handledBy: employee,
    });

    completeReturn(record);
    toast.success(`تم اعتماد المرتجع ${record.number} — رد ${fmtMoney(totals.value)} للعميل`);
    resetDraft();
    setTimeout(() => navigate("/cashier/returns/log"), 900);
  }

  // تحميل فاتورة محددة عند القدوم من تفاصيل الفاتورة.
  useEffect(() => {
    if (!invoiceParam) return;
    const found = invoices.find((i) => i.number.toLowerCase() === invoiceParam.toLowerCase());
    if (found) selectInvoice(found);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invoiceParam]);

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
      <ReturnHeaderBar number={nextReturnNumber()} employee={employee} employees={employees} onEmployeeChange={setEmployee} />

      <ExchangeInvoiceSearch
        term={term}
        onTermChange={(value) => {
          setTerm(value);
          setError("");
        }}
        onSubmit={submitSearch}
        error={error}
        invoice={invoice}
        matches={matches}
        quickPicks={quickPicks}
        onPick={selectInvoice}
        onClear={resetDraft}
      />

      <div ref={gridRef} className="grid gap-2 2xl:grid-cols-2">
        <div className="flex min-h-0 flex-col gap-1.5">
          <ReturnOriginalTable
            invoice={invoice}
            lines={lines}
            onStart={startReturn}
            onQty={setReturnQty}
            onQtyStep={stepReturnQty}
            onCancel={cancelReturn}
            totals={totals}
            minRows={fillRows}
          />

          <ReturnTotalsBar totals={totals} />
        </div>

        <div className="flex min-h-0 flex-col gap-1.5">
          <ReturnItemsTable
            lines={pickedLines}
            totals={totals}
            onQty={setReturnQty}
            onQtyStep={stepReturnQty}
            onRemove={(line) => cancelReturn(line.key)}
            minRows={fillRows}
          />

          <ReturnSettlementBar
            value={totals.value}
            reason={reason}
            onReasonChange={setReason}
            refundMethod={refundMethod}
            onRefundMethodChange={setRefundMethod}
          />
        </div>
      </div>

      <div ref={actionsRef}>
        <ReturnActionsBar
          canComplete={canComplete}
          hasDraft={hasDraft}
          onComplete={confirmReturn}
          onCancel={() => setCancelOpen(true)}
        />
      </div>

      <ConfirmDialog
        open={cancelOpen}
        onOpenChange={setCancelOpen}
        title="إلغاء عملية المرتجع"
        description="سيتم حذف الفاتورة المختارة والأصناف المحددة في هذه العملية، دون أي تأثير على المخزون أو تسجيل مرتجع."
        confirmLabel="إلغاء العملية"
        onConfirm={() => {
          resetDraft();
          toast.info("تم إلغاء عملية المرتجع");
        }}
      />
    </div>
  );
}