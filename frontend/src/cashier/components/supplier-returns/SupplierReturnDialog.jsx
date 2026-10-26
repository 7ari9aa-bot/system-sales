import { useEffect, useMemo, useState } from "react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import { Textarea } from "@/cashier/components/ui/textarea";
import { searchCatalog } from "@/cashier/api/catalogAdapter";
import { toMinor, mulMoney } from "@/cashier/api/money";
import { RETURN_SETTLEMENTS, SETTLEMENT_LABEL, buildReturn, parseCost, parseQuantity } from "@/cashier/api/purchasingAdapter";
import { fmtMoney } from "@/cashier/lib/format";

const EMPTY = { supplierId: "", orderId: "", variantId: "", search: "", qty: "1", unitCost: "", settlement: "credit", note: "" };

const SETTLEMENT_HINT = {
  credit: "بتتخصم من حساب المورد لما يوافق على المرتجع.",
  cash: "المورد بيرد الفلوس نقدًا. بنسجّل المبلغ في السجل فقط، ومفيش حركة بتتعمل على أي درج.",
  replace: "المورد بيبعت بضاعة بدالها. مفيش فلوس بتتحرك، والبضاعة الجديدة بتتسجل كفاتورة توريد.",
};

// تسجيل مرتجع لمورد. البضاعة بتخرج من المخزن فورًا، والفلوس ما بتتحركش غير لما المورد يقبل.
// مع فاتورة: السعر هو سعر الفاتورة والكمية المتاحة للإرجاع بتتحدد منها. من غير فاتورة: لازم تكتب السعر.
export default function SupplierReturnDialog({ open, onOpenChange, suppliers, orders, catalog, onSubmit, pending, error }) {
  const [form, setForm] = useState(EMPTY);
  const [localError, setLocalError] = useState("");

  useEffect(() => {
    if (!open) return;
    setForm(EMPTY);
    setLocalError("");
  }, [open]);

  const set = (field, value) => setForm((prev) => ({ ...prev, [field]: value }));
  const supplierOrders = useMemo(() => orders.filter((o) => o.supplierId === form.supplierId && o.receipt === "received"), [orders, form.supplierId]);
  const order = supplierOrders.find((o) => o.id === form.orderId) ?? null;
  // Against an order the choices are exactly what was bought on it; otherwise anything in the catalog.
  const candidates = order
    ? order.items.map((i) => ({ id: i.variantId, label: [i.name, i.color, i.size].filter(Boolean).join(" · "), max: i.qty, cost: i.unitCost }))
    : searchCatalog(catalog ?? [], form.search, 8).map((v) => ({ id: v.id, label: [v.productName, v.color, v.size].filter(Boolean).join(" · "), max: null, cost: "" }));
  const chosen = order ? candidates.find((c) => c.id === form.variantId) : (catalog ?? []).find((v) => v.id === form.variantId);
  const chosenLabel = order ? chosen?.label : chosen ? [chosen.productName, chosen.color, chosen.size].filter(Boolean).join(" · ") : "";
  const qty = parseQuantity(form.qty);
  const price = order ? chosen?.cost : parseCost(form.unitCost);
  const value = qty && price !== undefined && price !== null && price !== "" ? mulMoney(price, qty) : null;

  function submit() {
    const built = buildReturn({
      supplierId: form.supplierId,
      orderId: form.orderId || null,
      settlement: form.settlement,
      note: form.note,
      lines: form.variantId ? [{ variantId: form.variantId, qty: form.qty, unitCost: form.unitCost }] : [],
    });
    if (!built.ok) {
      setLocalError(built.error);
      return;
    }
    if (order && chosen?.max && qty > chosen.max) {
      setLocalError(`اللي اتشترى على الفاتورة دي ${chosen.max} بس`);
      return;
    }
    setLocalError("");
    onSubmit(built.payload);
  }

  const shown = localError || error;
  const sel = (value, onChange, placeholder, items) => (
    <Select value={value || "none"} onValueChange={(v) => onChange(v === "none" ? "" : v)}>
      <SelectTrigger><SelectValue placeholder={placeholder} /></SelectTrigger>
      <SelectContent>
        <SelectItem value="none">{placeholder}</SelectItem>
        {items.map(([k, label]) => <SelectItem key={k} value={k}>{label}</SelectItem>)}
      </SelectContent>
    </Select>
  );

  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <DialogContent dir="rtl" className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">تسجيل مرتجع للمورد</DialogTitle>
          <DialogDescription>البضاعة بتخرج من المخزن فورًا. التسوية بتتسجّل على حساب المورد لما يوافق، ومفيش حركة على أي درج.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">المورد</Label>
            {sel(form.supplierId, (v) => setForm((p) => ({ ...p, supplierId: v, orderId: "", variantId: "" })), "اختر المورد", suppliers.map((s) => [s.id, s.name]))}
          </div>
          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">فاتورة التوريد (اختياري)</Label>
            {sel(form.orderId, (v) => setForm((p) => ({ ...p, orderId: v, variantId: "", unitCost: "" })), "بدون ربط بفاتورة", supplierOrders.map((o) => [o.id, o.number]))}
          </div>
          <div className="sm:col-span-2">
            <Label className="mb-1.5 block text-xs text-muted-foreground">{order ? "الصنف (من بنود الفاتورة)" : "الصنف"}</Label>
            {order ? (
              sel(form.variantId, (v) => set("variantId", v), "اختر الصنف", candidates.map((c) => [c.id, `${c.label} (اتشترى ${c.max})`]))
            ) : (
              <div className="relative">
                <Input value={chosenLabel || form.search} placeholder="ابحث بالاسم أو الباركود أو الكود" onChange={(e) => setForm((p) => ({ ...p, variantId: "", search: e.target.value }))} />
                {!form.variantId && candidates.length > 0 && form.search.trim() && (
                  <ul className="absolute z-20 mt-1 max-h-48 w-full overflow-y-auto rounded-md border border-border bg-popover p-1 shadow-md">
                    {candidates.map((c) => (
                      <li key={c.id}>
                        <button type="button" className="w-full rounded px-2 py-1.5 text-start text-sm hover:bg-muted" onClick={() => setForm((p) => ({ ...p, variantId: c.id, search: "" }))}>{c.label}</button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">الكمية المرتجعة</Label>
            <Input inputMode="numeric" className="num" value={form.qty} onChange={(e) => set("qty", e.target.value)} />
          </div>
          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">سعر الشراء للقطعة</Label>
            {order ? (
              <p className="num flex h-9 items-center rounded-md border border-dashed border-border px-3 text-sm text-muted-foreground">{chosen ? fmtMoney(chosen.cost) : "—"} (سعر الفاتورة)</p>
            ) : (
              <Input inputMode="decimal" className="num" value={form.unitCost} onChange={(e) => set("unitCost", e.target.value)} placeholder="0.00" />
            )}
          </div>
          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">التسوية</Label>
            <Select value={form.settlement} onValueChange={(v) => set("settlement", v)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>{RETURN_SETTLEMENTS.map((k) => <SelectItem key={k} value={k}>{SETTLEMENT_LABEL[k]}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <p className="text-[11px] text-muted-foreground sm:col-span-2">{SETTLEMENT_HINT[form.settlement]}</p>
          <div className="sm:col-span-2">
            <Label className="mb-1.5 block text-xs text-muted-foreground">ملاحظات</Label>
            <Textarea rows={2} maxLength={255} value={form.note} onChange={(e) => set("note", e.target.value)} placeholder="ملاحظة على الإرجاع أو الاتفاق مع المورد" />
          </div>
        </div>
        {shown && <p role="alert" className="rounded-md border border-[#F1C7C3] bg-[#FDECEA] px-3 py-2 text-xs font-semibold text-[#B3261E]">{shown}</p>}
        <DialogFooter className="flex-wrap gap-2 sm:justify-between">
          <p className="num text-sm">قيمة المرتجع: <span className="font-heading text-base font-bold">{value ? fmtMoney(value) : "—"}</span></p>
          <div className="flex gap-2">
            <Button variant="outline" disabled={pending} onClick={() => onOpenChange(false)}>رجوع</Button>
            <Button className="font-bold" disabled={pending} onClick={submit}>{pending ? "جارٍ التسجيل..." : "تسجيل المرتجع"}</Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
