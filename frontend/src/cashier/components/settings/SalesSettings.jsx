import { useState } from "react";
import { Percent, Save } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import { Switch } from "@/cashier/components/ui/switch";
import SectionCard from "@/cashier/components/ui-kit/SectionCard";
import { PAYMENT_METHODS } from "@/cashier/lib/format";
import { ALL_PAYMENT_METHODS, updateSalesSettings, useSalesSettings } from "@/cashier/lib/salesSettings";

const HINTS = {
  cash: "خصم فوري من درج الكاشير",
  card: "فيزا / ماستركارد",
  wallet: "فودافون كاش / إنستاپاي",
  credit: "يُسجَّل على حساب العميل",
};

// طرق الدفع المتاحة في الكاشير وحد الخصم المسموح للكاشير.
export default function SalesSettings() {
  const saved = useSalesSettings();
  const [form, setForm] = useState(saved);

  function toggleMethod(key, value) {
    setForm((prev) => {
      const enabledMethods = value ? [...prev.enabledMethods, key] : prev.enabledMethods.filter((m) => m !== key);
      if (enabledMethods.length === 0) {
        toast.error("يجب تفعيل طريقة دفع واحدة على الأقل");
        return prev;
      }
      return {
        ...prev,
        enabledMethods,
        defaultMethod: enabledMethods.includes(prev.defaultMethod) ? prev.defaultMethod : enabledMethods[0],
      };
    });
  }

  return (
    <SectionCard
      title="طرق الدفع وحدود الخصم"
      description="طرق الدفع الظاهرة في الكاشير، الطريقة الافتراضية، وأقصى خصم يمنحه الكاشير"
      action={
        <Button
          className="gap-2"
          onClick={() => {
            updateSalesSettings(form);
            toast.success("تم حفظ طرق الدفع وحدود الخصم");
          }}
        >
          <Save className="h-4 w-4" />
          حفظ
        </Button>
      }
    >
      <div className="grid gap-2 sm:grid-cols-2">
        {ALL_PAYMENT_METHODS.map((key) => (
          <div key={key} className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2.5">
            <div className="min-w-0">
              <p className="text-sm font-medium">{PAYMENT_METHODS[key].label}</p>
              <p className="text-[11px] text-muted-foreground">{HINTS[key]}</p>
            </div>
            <Switch checked={form.enabledMethods.includes(key)} onCheckedChange={(v) => toggleMethod(key, v)} />
          </div>
        ))}
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div>
          <Label className="mb-1.5 block text-xs text-muted-foreground">الطريقة الافتراضية في الكاشير</Label>
          <Select value={form.defaultMethod} onValueChange={(v) => setForm((p) => ({ ...p, defaultMethod: v }))}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {form.enabledMethods.map((key) => (
                <SelectItem key={key} value={key}>
                  {PAYMENT_METHODS[key].label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label className="mb-1.5 block text-xs text-muted-foreground">أقصى نسبة خصم مسموحة للكاشير (%)</Label>
          <Input
            type="number"
            min={0}
            max={100}
            value={form.maxDiscountPct}
            onChange={(e) => setForm((p) => ({ ...p, maxDiscountPct: Math.max(0, Math.min(100, Number(e.target.value) || 0)) }))}
            className="num"
          />
        </div>
      </div>

      <p className="mt-4 flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Percent className="h-3.5 w-3.5" />
        الكاشير لا يتجاوز حد الخصم المحفوظ هنا — أي نسبة أكبر تُصحَّح تلقائيًا مع تنبيه.
      </p>
    </SectionCard>
  );
}