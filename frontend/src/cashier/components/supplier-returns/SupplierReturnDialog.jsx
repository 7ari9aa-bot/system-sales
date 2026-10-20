import { useEffect, useState } from "react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import { Textarea } from "@/cashier/components/ui/textarea";
import { products, suppliers } from "@/cashier/lib/mockData";
import { purchaseOrders } from "@/cashier/lib/purchasesData";
import { SUPPLIER_RETURN_REASONS, SUPPLIER_RETURN_SETTLEMENTS, fmtMoney } from "@/cashier/lib/format";

const EMPTY = { supplierId: "", poId: "", productId: "", variantId: "", qty: "1", unitCost: "", reason: "", settlement: "credit", note: "" };

// تسجيل إرجاع بضاعة إلى المورد: الصنف والكمية والسبب وتسوية الحساب.
export default function SupplierReturnDialog({ open, onOpenChange, onSubmit }) {
  const [form, setForm] = useState(EMPTY);

  useEffect(() => {
    if (open) setForm(EMPTY);
  }, [open]);

  const product = products.find((p) => p.id === form.productId) ?? null;
  const variant = product?.variants.find((v) => v.id === form.variantId) ?? null;
  const orderOptions = purchaseOrders.filter((o) => o.supplierId === form.supplierId);
  const qty = Number(form.qty) || 0;
  const unitCost = Number(form.unitCost) || 0;
  const canSubmit = form.supplierId && product && variant && qty > 0 && unitCost > 0 && form.reason && form.settlement;

  function set(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  function pickProduct(productId) {
    const next = products.find((p) => p.id === productId);
    const firstVariant = next?.variants[0];
    setForm((prev) => ({ ...prev, productId, variantId: firstVariant?.id ?? "", unitCost: String(firstVariant?.buyPrice ?? "") }));
  }

  function pickVariant(variantId) {
    const next = product?.variants.find((v) => v.id === variantId);
    setForm((prev) => ({ ...prev, variantId, unitCost: String(next?.buyPrice ?? prev.unitCost) }));
  }

  function submit() {
    const supplier = suppliers.find((s) => s.id === form.supplierId);
    const order = purchaseOrders.find((o) => o.id === form.poId);
    onSubmit({
      supplierId: form.supplierId,
      supplierName: supplier?.name ?? "—",
      poNumber: order?.number ?? "—",
      productName: product.name,
      sku: variant.sku,
      color: variant.color,
      size: variant.size,
      qty,
      unitCost,
      amount: +(unitCost * qty).toFixed(2),
      reason: form.reason,
      settlement: form.settlement,
      employee: order?.employee ?? "منى عبد الله",
      note: form.note,
    });
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">تسجيل مرتجع للمورد</DialogTitle>
          <DialogDescription>اختر الصنف والكمية والسبب، وحدّد طريقة تسوية الحساب مع المورد.</DialogDescription>
        </DialogHeader>

        <div className="grid max-h-[58vh] gap-3 overflow-y-auto scroll-slim pe-1 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <Label className="mb-1.5 block text-xs text-muted-foreground">المورد</Label>
            <Select value={form.supplierId || "none"} onValueChange={(v) => setForm((prev) => ({ ...prev, supplierId: v === "none" ? "" : v, poId: "" }))}>
              <SelectTrigger>
                <SelectValue placeholder="اختر المورد" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">اختر المورد</SelectItem>
                {suppliers.map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    {s.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="sm:col-span-2">
            <Label className="mb-1.5 block text-xs text-muted-foreground">فاتورة التوريد (اختياري)</Label>
            <Select value={form.poId || "none"} onValueChange={(v) => set("poId", v === "none" ? "" : v)}>
              <SelectTrigger>
                <SelectValue placeholder="بدون ربط بفاتورة" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">بدون ربط بفاتورة</SelectItem>
                {orderOptions.map((o) => (
                  <SelectItem key={o.id} value={o.id}>
                    {o.number} • {o.pieces} قطعة
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">المنتج</Label>
            <Select value={form.productId || "none"} onValueChange={(v) => pickProduct(v === "none" ? "" : v)}>
              <SelectTrigger>
                <SelectValue placeholder="اختر المنتج" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">اختر المنتج</SelectItem>
                {products.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">اللون والمقاس</Label>
            <Select value={form.variantId || "none"} onValueChange={(v) => pickVariant(v === "none" ? "" : v)} disabled={!product}>
              <SelectTrigger>
                <SelectValue placeholder="اختر المتغير" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">اختر المتغير</SelectItem>
                {(product?.variants ?? []).map((v) => (
                  <SelectItem key={v.id} value={v.id}>
                    {v.color} / {v.size} — رصيد {v.stock}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">الكمية المرتجعة</Label>
            <Input type="number" min={1} value={form.qty} onChange={(e) => set("qty", e.target.value)} className="num" />
          </div>

          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">سعر التكلفة للقطعة</Label>
            <Input type="number" min={0} value={form.unitCost} onChange={(e) => set("unitCost", e.target.value)} className="num" />
          </div>

          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">سبب الإرجاع</Label>
            <Select value={form.reason || "none"} onValueChange={(v) => set("reason", v === "none" ? "" : v)}>
              <SelectTrigger>
                <SelectValue placeholder="اختر السبب" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">اختر السبب</SelectItem>
                {SUPPLIER_RETURN_REASONS.map((r) => (
                  <SelectItem key={r} value={r}>
                    {r}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">تسوية الحساب</Label>
            <Select value={form.settlement} onValueChange={(v) => set("settlement", v)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(SUPPLIER_RETURN_SETTLEMENTS).map(([key, s]) => (
                  <SelectItem key={key} value={key}>
                    {s.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="sm:col-span-2">
            <Label className="mb-1.5 block text-xs text-muted-foreground">ملاحظات</Label>
            <Textarea rows={2} value={form.note} onChange={(e) => set("note", e.target.value)} placeholder="ملاحظة على الإرجاع أو الاتفاق مع المورد" />
          </div>
        </div>

        <DialogFooter className="flex-wrap gap-2 sm:justify-between">
          <p className="num text-xs text-muted-foreground">
            قيمة المرتجع: <span className="font-bold text-foreground">{fmtMoney(qty * unitCost)}</span>
          </p>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              إلغاء
            </Button>
            <Button className="font-bold" disabled={!canSubmit} onClick={submit}>
              تسجيل المرتجع
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}