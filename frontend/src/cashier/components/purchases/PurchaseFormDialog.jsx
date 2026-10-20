import { useState } from "react";
import { Plus, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import ColorSwatch from "@/cashier/components/ui-kit/ColorSwatch";
import { supplierRows } from "@/cashier/lib/opsData";
import { branches, colorHex, products } from "@/cashier/lib/mockData";
import { fmtInt, fmtMoney } from "@/cashier/lib/format";

// تسجيل فاتورة توريد جديدة: المورد، بنود البضاعة وتكاليفها، والمبلغ المدفوع.
export default function PurchaseFormDialog({ open, onOpenChange, onSave, nextNumber }) {
  const [supplierId, setSupplierId] = useState(supplierRows[0].id);
  const [warehouse, setWarehouse] = useState(branches[0]);
  const [date, setDate] = useState("2026-10-19");
  const [productId, setProductId] = useState(products[0].id);
  const [color, setColor] = useState(products[0].colors[0]);
  const [size, setSize] = useState(products[0].variants[0].size);
  const [qty, setQty] = useState(1);
  const [unitCost, setUnitCost] = useState(products[0].buyPrice);
  const [lines, setLines] = useState([]);
  const [paid, setPaid] = useState(0);
  const [note, setNote] = useState("");

  const product = products.find((p) => p.id === productId) ?? products[0];
  const activeColor = product.colors.includes(color) ? color : product.colors[0];
  const sizeOptions = product.variants.filter((v) => v.color === activeColor).map((v) => v.size);
  const activeSize = sizeOptions.includes(size) ? size : sizeOptions[0];
  const total = +lines.reduce((s, l) => s + l.total, 0).toFixed(2);

  function changeProduct(id) {
    const next = products.find((p) => p.id === id) ?? products[0];
    setProductId(id);
    setColor(next.colors[0]);
    setSize(next.variants.find((v) => v.color === next.colors[0])?.size ?? next.variants[0].size);
    setUnitCost(next.buyPrice);
  }

  function addLine() {
    const q = Math.max(1, Number(qty) || 1);
    const cost = Math.max(0, Number(unitCost) || 0);
    setLines((prev) => [
      ...prev,
      {
        id: `${product.id}-${activeColor}-${activeSize}-${prev.length}`,
        name: product.name,
        color: activeColor,
        size: activeSize,
        qty: q,
        unitCost: cost,
        total: +(cost * q).toFixed(2),
      },
    ]);
    setQty(1);
  }

  function reset() {
    setLines([]);
    setPaid(0);
    setNote("");
  }

  function save() {
    if (lines.length === 0) {
      toast.error("أضف بندًا واحدًا على الأقل قبل الحفظ");
      return;
    }
    const paidValue = Math.min(total, Math.max(0, Number(paid) || 0));
    onSave({
      id: `po-new-${Date.now()}`,
      number: nextNumber,
      date: `${date}T10:00:00`,
      supplierId,
      supplierName: supplierRows.find((s) => s.id === supplierId)?.name ?? "—",
      items: lines.map((l) => ({ name: l.name, color: l.color, size: l.size, qty: l.qty, unitCost: l.unitCost, total: l.total })),
      pieces: lines.reduce((s, l) => s + l.qty, 0),
      total,
      paid: paidValue,
      balance: +(total - paidValue).toFixed(2),
      warehouse,
      employee: "منى عبد الله",
      status: paidValue >= total ? "received" : paidValue > 0 ? "partial" : "pending",
      note,
    });
    reset();
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-h-[92vh] max-w-3xl overflow-y-auto scroll-slim">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">تسجيل توريد جديد</DialogTitle>
          <DialogDescription>
            فاتورة <span className="num">{nextNumber}</span> — أدخل بنود البضاعة الداخلة وتكلفتها ثم احفظ لتحديث المخزون.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">المورد</Label>
            <Select value={supplierId} onValueChange={setSupplierId}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {supplierRows.map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    {s.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">المخزن المستلم</Label>
            <Select value={warehouse} onValueChange={setWarehouse}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {branches.map((b) => (
                  <SelectItem key={b} value={b}>
                    {b}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">تاريخ التوريد</Label>
            <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </div>
        </div>

        <div className="rounded-xl border border-border p-3">
          <p className="mb-2 text-xs font-semibold text-muted-foreground">إضافة بند</p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
            <div className="lg:col-span-2">
              <Select value={productId} onValueChange={changeProduct}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {products.map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Select value={activeColor} onValueChange={setColor}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {product.colors.map((c) => (
                  <SelectItem key={c} value={c}>
                    {c}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={activeSize} onValueChange={setSize}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {sizeOptions.map((s) => (
                  <SelectItem key={s} value={s}>
                    {s}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input type="number" min={1} value={qty} onChange={(e) => setQty(e.target.value)} className="num" aria-label="الكمية" placeholder="الكمية" />
            <Input
              type="number"
              min={0}
              value={unitCost}
              onChange={(e) => setUnitCost(e.target.value)}
              className="num"
              aria-label="تكلفة الوحدة"
              placeholder="تكلفة الوحدة"
            />
          </div>
          <Button variant="outline" className="mt-3 gap-2" onClick={addLine}>
            <Plus className="h-4 w-4" />
            إضافة البند
          </Button>
        </div>

        {lines.length > 0 && (
          <div className="overflow-x-auto scroll-slim rounded-xl border border-border">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="bg-muted/50 text-xs text-muted-foreground">
                  <th className="px-3 py-2 text-start font-semibold">الصنف</th>
                  <th className="px-3 py-2 text-center font-semibold">الكمية</th>
                  <th className="px-3 py-2 text-start font-semibold">تكلفة الوحدة</th>
                  <th className="px-3 py-2 text-start font-semibold">الإجمالي</th>
                  <th className="px-3 py-2 text-center font-semibold">حذف</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {lines.map((l) => (
                  <tr key={l.id}>
                    <td className="px-3 py-2">
                      <span className="block font-medium">{l.name}</span>
                      <span className="flex items-center gap-2 text-[11px] text-muted-foreground">
                        <ColorSwatch color={l.color} hex={colorHex(l.color)} showLabel={false} />
                        مقاس {l.size}
                      </span>
                    </td>
                    <td className="num px-3 py-2 text-center">{fmtInt(l.qty)}</td>
                    <td className="num px-3 py-2">{fmtMoney(l.unitCost)}</td>
                    <td className="num px-3 py-2 font-semibold">{fmtMoney(l.total)}</td>
                    <td className="px-3 py-2 text-center">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-rose-600 hover:bg-rose-50"
                        aria-label="حذف البند"
                        onClick={() => setLines((prev) => prev.filter((x) => x.id !== l.id))}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">المبلغ المدفوع للمورد</Label>
            <Input type="number" min={0} value={paid} onChange={(e) => setPaid(e.target.value)} className="num font-bold" />
          </div>
          <div className="rounded-lg bg-muted/50 px-3 py-2">
            <p className="text-[11px] text-muted-foreground">إجمالي الفاتورة</p>
            <p className="num font-heading text-base font-bold">{fmtMoney(total)}</p>
          </div>
          <div className="rounded-lg bg-amber-50 px-3 py-2">
            <p className="text-[11px] text-amber-800">المستحق للمورد</p>
            <p className="num font-heading text-lg font-bold text-amber-700">{fmtMoney(Math.max(0, total - (Number(paid) || 0)))}</p>
          </div>
        </div>

        <div>
          <Label className="mb-1.5 block text-xs text-muted-foreground">ملاحظات (اختياري)</Label>
          <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="مثال: الشحن على المورد" />
        </div>

        <div className="flex gap-2">
          <Button variant="outline" className="flex-1" onClick={() => onOpenChange(false)}>
            إلغاء
          </Button>
          <Button className="flex-1 gap-2 font-bold" onClick={save}>
            <Save className="h-4 w-4" />
            حفظ فاتورة التوريد
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}