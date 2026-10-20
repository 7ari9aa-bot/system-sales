import { useEffect, useMemo, useState } from "react";
import { Plus, Save, Trash2 } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import { searchCatalog } from "@/cashier/api/catalogAdapter";
import { addLine, buildPurchaseOrder, linesTotal, parseCost, piecesOf } from "@/cashier/api/purchasingAdapter";
import { shopToday } from "@/cashier/lib/period";
import { fmtInt, fmtMoney } from "@/cashier/lib/format";

const blank = () => ({ supplierId: "", date: shopToday(), lines: [], note: "", receiveNow: true });

// تسجيل فاتورة توريد: المورد، بنود البضاعة وتكلفتها. بتتسجل كبضاعة وصلت فعلًا (بتدخل المخزن فورًا)،
// والدفع منفصل: تقدر تدفع دلوقتي أو بعدين من تفاصيل الفاتورة.
export default function PurchaseFormDialog({ open, onOpenChange, suppliers, catalog, onSubmit, pending, error }) {
  const [form, setForm] = useState(blank);
  const [term, setTerm] = useState("");
  const [picked, setPicked] = useState(null);
  const [qty, setQty] = useState("1");
  const [unitCost, setUnitCost] = useState("");
  const [localError, setLocalError] = useState("");

  useEffect(() => {
    if (!open) return;
    setForm(blank());
    setTerm("");
    setPicked(null);
    setQty("1");
    setUnitCost("");
    setLocalError("");
  }, [open]);

  const matches = useMemo(() => searchCatalog(catalog ?? [], term, 8), [catalog, term]);
  const set = (field, value) => setForm((prev) => ({ ...prev, [field]: value }));
  const total = linesTotal(form.lines);

  function pick(v) {
    setPicked(v);
    setTerm("");
    setLocalError("");
  }

  function add() {
    if (!picked) {
      setLocalError("ابحث عن الصنف واختاره الأول");
      return;
    }
    const label = [picked.productName, picked.color, picked.size].filter(Boolean).join(" · ");
    const r = addLine(form.lines, { variantId: picked.id, label, qty, unitCost });
    if (!r.ok) {
      setLocalError(r.error);
      return;
    }
    setLocalError("");
    set("lines", r.lines);
    setPicked(null);
    setQty("1");
    setUnitCost("");
  }

  function submit() {
    const built = buildPurchaseOrder(form);
    if (!built.ok) {
      setLocalError(built.error);
      return;
    }
    setLocalError("");
    onSubmit(built.payload);
  }

  const shown = localError || error;
  const costPreview = parseCost(unitCost);

  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <DialogContent dir="rtl" className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">تسجيل توريد جديد</DialogTitle>
          <DialogDescription>
            البضاعة بتدخل المخزن فور الحفظ وسعر الشراء بيدخل في متوسط تكلفة الصنف. الدفع منفصل وتقدر تسجّله بعد كده.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-3 sm:grid-cols-3">
          <div className="sm:col-span-2">
            <Label className="mb-1.5 block text-xs text-muted-foreground">المورد</Label>
            <Select value={form.supplierId || "none"} onValueChange={(v) => set("supplierId", v === "none" ? "" : v)}>
              <SelectTrigger><SelectValue placeholder="اختر المورد" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="none">اختر المورد</SelectItem>
                {suppliers.filter((s) => s.status === "active").map((s) => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}
              </SelectContent>
            </Select>
            {suppliers.length === 0 && <p className="mt-1 text-[11px] text-muted-foreground">مفيش موردين لسه: أضف مورد من صفحة الموردين الأول.</p>}
          </div>
          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">تاريخ الفاتورة</Label>
            <Input type="date" value={form.date} onChange={(e) => set("date", e.target.value)} />
          </div>
        </div>

        <div className="rounded-xl border border-border p-3">
          <p className="mb-2 text-xs font-bold text-muted-foreground">إضافة بند</p>
          <div className="grid gap-2 sm:grid-cols-[1fr_90px_120px_auto]">
            <div className="relative">
              <Input
                value={picked ? [picked.productName, picked.color, picked.size].filter(Boolean).join(" · ") : term}
                onChange={(e) => {
                  setPicked(null);
                  setTerm(e.target.value);
                }}
                placeholder="ابحث بالاسم أو الباركود أو الكود"
              />
              {!picked && matches.length > 0 && (
                <ul className="absolute z-20 mt-1 max-h-56 w-full overflow-y-auto rounded-md border border-border bg-popover p-1 shadow-md">
                  {matches.map((v) => (
                    <li key={v.id}>
                      <button type="button" className="flex w-full items-center justify-between rounded px-2 py-1.5 text-start text-sm hover:bg-muted" onClick={() => pick(v)}>
                        <span>{[v.productName, v.color, v.size].filter(Boolean).join(" · ")}</span>
                        <span className="num text-[11px] text-muted-foreground">{v.sku}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <Input inputMode="numeric" className="num" value={qty} onChange={(e) => setQty(e.target.value)} placeholder="الكمية" />
            <Input inputMode="decimal" className="num" value={unitCost} onChange={(e) => setUnitCost(e.target.value)} placeholder="سعر الشراء" />
            <Button type="button" variant="outline" onClick={add}><Plus />إضافة</Button>
          </div>
          {costPreview && <p className="num mt-1 text-[11px] text-muted-foreground">سعر الوحدة: {fmtMoney(costPreview)}</p>}
        </div>

        <div className="max-h-[28vh] overflow-y-auto scroll-slim rounded-xl border border-border">
          {form.lines.length === 0 ? (
            <p className="px-3 py-6 text-center text-sm text-muted-foreground">لسه مفيش بنود. ابحث عن صنف وأضفه.</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-muted/70 backdrop-blur">
                <tr className="text-xs text-muted-foreground">
                  <th className="px-3 py-2 text-start font-semibold">الصنف</th>
                  <th className="px-3 py-2 text-center font-semibold">الكمية</th>
                  <th className="px-3 py-2 text-start font-semibold">سعر الوحدة</th>
                  <th className="px-3 py-2 text-start font-semibold">الإجمالي</th>
                  <th className="w-10" />
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {form.lines.map((l) => (
                  <tr key={l.variantId}>
                    <td className="px-3 py-2 font-medium">{l.label}</td>
                    <td className="num px-3 py-2 text-center">{fmtInt(l.qty)}</td>
                    <td className="num px-3 py-2">{fmtMoney(l.unitCost)}</td>
                    <td className="num px-3 py-2 font-semibold">{fmtMoney(l.total)}</td>
                    <td className="px-2">
                      <Button type="button" variant="ghost" aria-label="حذف البند" onClick={() => set("lines", form.lines.filter((x) => x.variantId !== l.variantId))}><Trash2 /></Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div>
          <Label className="mb-1.5 block text-xs text-muted-foreground">ملاحظة (اختياري)</Label>
          <Input value={form.note} maxLength={255} onChange={(e) => set("note", e.target.value)} />
        </div>

        {shown && <p role="alert" className="rounded-md border border-[#F1C7C3] bg-[#FDECEA] px-3 py-2 text-xs font-semibold text-[#B3261E]">{shown}</p>}

        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="num text-sm">
            {fmtInt(piecesOf(form.lines))} قطعة • الإجمالي <span className="font-heading text-base font-bold">{fmtMoney(total)}</span>
          </p>
          <div className="flex gap-2">
            <Button variant="outline" disabled={pending} onClick={() => onOpenChange(false)}>رجوع</Button>
            <Button className="font-bold" disabled={pending || form.lines.length === 0} onClick={submit}>
              <Save />
              {pending ? "جارٍ الحفظ..." : "حفظ واستلام البضاعة"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
