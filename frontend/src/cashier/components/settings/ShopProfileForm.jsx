import { useState } from "react";
import { Save } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import SectionCard from "@/cashier/components/ui-kit/SectionCard";
import { shop } from "@/cashier/lib/mockData";

// بيانات المحل الأساسية — تظهر في الفاتورة والتقارير.
export default function ShopProfileForm() {
  const [form, setForm] = useState({ ...shop });

  function set(key, value) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  return (
    <SectionCard
      title="بيانات المحل"
      description="الاسم والعنوان والبيانات الضريبية المستخدمة في الفاتورة والتقارير"
      action={
        <Button className="gap-2" onClick={() => toast.success("تم حفظ بيانات المحل")}>
          <Save className="h-4 w-4" />
          حفظ
        </Button>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <Label className="mb-1.5 block text-xs text-muted-foreground">اسم المحل</Label>
          <Input value={form.name} onChange={(e) => set("name", e.target.value)} />
        </div>
        <div>
          <Label className="mb-1.5 block text-xs text-muted-foreground">الفرع</Label>
          <Input value={form.branch} onChange={(e) => set("branch", e.target.value)} />
        </div>
        <div className="sm:col-span-2">
          <Label className="mb-1.5 block text-xs text-muted-foreground">العنوان</Label>
          <Input value={form.address} onChange={(e) => set("address", e.target.value)} />
        </div>
        <div>
          <Label className="mb-1.5 block text-xs text-muted-foreground">الهاتف</Label>
          <Input value={form.phone} onChange={(e) => set("phone", e.target.value)} className="num" />
        </div>
        <div>
          <Label className="mb-1.5 block text-xs text-muted-foreground">الرقم الضريبي</Label>
          <Input value={form.taxId} onChange={(e) => set("taxId", e.target.value)} className="num" />
        </div>
        <div>
          <Label className="mb-1.5 block text-xs text-muted-foreground">العملة</Label>
          <Input value={form.currency} onChange={(e) => set("currency", e.target.value)} />
        </div>
        <div>
          <Label className="mb-1.5 block text-xs text-muted-foreground">حد إعادة الطلب (قطعة)</Label>
          <Input
            type="number"
            min={0}
            value={form.lowStockThreshold}
            onChange={(e) => set("lowStockThreshold", Number(e.target.value) || 0)}
            className="num"
          />
        </div>
      </div>
    </SectionCard>
  );
}