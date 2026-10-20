import { useState } from "react";
import { Printer, Save } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import { Switch } from "@/cashier/components/ui/switch";
import SectionCard from "@/cashier/components/ui-kit/SectionCard";

function ToggleRow({ label, hint, checked, onCheckedChange }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2.5">
      <div className="min-w-0">
        <p className="text-sm font-medium">{label}</p>
        <p className="text-[11px] text-muted-foreground">{hint}</p>
      </div>
      <Switch checked={checked} onCheckedChange={onCheckedChange} />
    </div>
  );
}

// إعدادات شكل الفاتورة المطبوعة والباركود.
export default function PrintAndBarcodeSettings() {
  const [cfg, setCfg] = useState({
    headerNote: "",
    footerNote: "شكرًا لتعاملكم معنا • الاستبدال خلال ١٤ يومًا بشرط وجود الفاتورة",
    paper: "80mm",
    copies: 1,
    showTaxId: true,
    printLogo: true,
    barcodePrefix: "200",
    labelSize: "38x25",
    showPriceOnLabel: true,
    autoGenerateBarcode: true,
  });

  function set(key, value) {
    setCfg((c) => ({ ...c, [key]: value }));
  }

  return (
    <SectionCard
      title="الفاتورة والباركود"
      description="شكل الفاتورة المطبوعة، مقاس الورق، وإعدادات توليد الباركود على الملصقات"
      action={
        <Button className="gap-2" onClick={() => toast.success("تم حفظ إعدادات الفاتورة والباركود")}>
          <Save className="h-4 w-4" />
          حفظ
        </Button>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <Label className="mb-1.5 block text-xs text-muted-foreground">سطر أعلى الفاتورة</Label>
          <Input value={cfg.headerNote} onChange={(e) => set("headerNote", e.target.value)} placeholder="مثال: اسم المحل أو الفرع" />
        </div>
        <div className="sm:col-span-2">
          <Label className="mb-1.5 block text-xs text-muted-foreground">سطر أسفل الفاتورة</Label>
          <Input value={cfg.footerNote} onChange={(e) => set("footerNote", e.target.value)} />
        </div>
        <div>
          <Label className="mb-1.5 block text-xs text-muted-foreground">مقاس ورق الطابعة</Label>
          <Select value={cfg.paper} onValueChange={(v) => set("paper", v)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="58mm">حراري ٥٨ مم</SelectItem>
              <SelectItem value="80mm">حراري ٨٠ مم</SelectItem>
              <SelectItem value="a4">ورق A4</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label className="mb-1.5 block text-xs text-muted-foreground">عدد نسخ الفاتورة</Label>
          <Input type="number" min={1} max={3} value={cfg.copies} onChange={(e) => set("copies", Number(e.target.value) || 1)} className="num" />
        </div>
        <div>
          <Label className="mb-1.5 block text-xs text-muted-foreground">بادئة أكواد الباركود</Label>
          <Input value={cfg.barcodePrefix} onChange={(e) => set("barcodePrefix", e.target.value)} className="num" />
        </div>
        <div>
          <Label className="mb-1.5 block text-xs text-muted-foreground">مقاس ملصق الباركود</Label>
          <Select value={cfg.labelSize} onValueChange={(v) => set("labelSize", v)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="38x25">ملصق ٣٨ × ٢٥ مم</SelectItem>
              <SelectItem value="50x30">ملصق ٥٠ × ٣٠ مم</SelectItem>
              <SelectItem value="a4">ورق A4 — مقاس كامل</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-2">
        <ToggleRow
          label="طباعة الرقم الضريبي"
          hint="يظهر أسفل بيانات المحل في الفاتورة"
          checked={cfg.showTaxId}
          onCheckedChange={(v) => set("showTaxId", v)}
        />
        <ToggleRow label="طباعة شعار المحل" hint="يُطبع الشعار أعلى الفاتورة" checked={cfg.printLogo} onCheckedChange={(v) => set("printLogo", v)} />
        <ToggleRow
          label="طباعة السعر على الملصق"
          hint="يظهر سعر البيع أسفل الباركود"
          checked={cfg.showPriceOnLabel}
          onCheckedChange={(v) => set("showPriceOnLabel", v)}
        />
        <ToggleRow
          label="توليد الباركود تلقائيًا"
          hint="يُنشأ كود لكل متغير لون ومقاس عند إضافة منتج"
          checked={cfg.autoGenerateBarcode}
          onCheckedChange={(v) => set("autoGenerateBarcode", v)}
        />
      </div>

      <p className="mt-4 flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Printer className="h-3.5 w-3.5" />
        يمكنك معاينة الطباعة من شاشة الكاشير أو من ملصقات المنتجات.
      </p>
    </SectionCard>
  );
}