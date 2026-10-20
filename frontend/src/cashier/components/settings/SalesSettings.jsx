import { useState } from "react";
import { Percent, Save } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import SectionCard from "@/cashier/components/ui-kit/SectionCard";
import { updateSalesSettings, useSalesSettings } from "@/cashier/lib/salesSettings";

// حد الخصم المسموح للكاشير. (لا توجد إعدادات طرق دفع: كل البيع نقدي حاليًا.)
export default function SalesSettings() {
  const saved = useSalesSettings();
  const [maxDiscountPct, setMaxDiscountPct] = useState(saved.maxDiscountPct);

  return (
    <SectionCard
      title="حدود الخصم"
      description="أقصى خصم يمنحه الكاشير على الفاتورة أو الصنف"
      action={
        <Button
          className="gap-2"
          onClick={() => {
            updateSalesSettings({ maxDiscountPct });
            toast.success("تم حفظ حد الخصم");
          }}
        >
          <Save className="h-4 w-4" />
          حفظ
        </Button>
      }
    >
      <div className="max-w-xs">
        <Label htmlFor="max-discount" className="mb-1.5 block text-xs text-muted-foreground">أقصى نسبة خصم مسموحة للكاشير (%)</Label>
        <Input
          id="max-discount"
          type="number"
          min={0}
          max={100}
          value={maxDiscountPct}
          onChange={(e) => setMaxDiscountPct(Math.max(0, Math.min(100, Number(e.target.value) || 0)))}
          className="num"
        />
      </div>

      <p className="mt-4 flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Percent className="h-3.5 w-3.5" />
        الكاشير لا يتجاوز حد الخصم المحفوظ هنا — أي نسبة أكبر تُصحَّح تلقائيًا مع تنبيه.
      </p>
    </SectionCard>
  );
}
