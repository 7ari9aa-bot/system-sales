import { FileSpreadsheet, Info, Loader2, Upload } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { exportCsv } from "@/cashier/lib/exportCsv";
import { buildProductsFromRows } from "@/cashier/lib/importProducts";
import { readProductsFile } from "@/cashier/lib/readProductsFile";
import { fmtInt, fmtMoney } from "@/cashier/lib/format";

const TEMPLATE_COLUMNS = [
  { header: "اسم المنتج", key: "name" },
  { header: "التصنيف", key: "category" },
  { header: "العلامة التجارية", key: "brand" },
  { header: "اللون", key: "color" },
  { header: "المقاس", key: "size" },
  { header: "SKU", key: "sku" },
  { header: "الباركود", key: "barcode" },
  { header: "سعر الشراء", key: "buyPrice" },
  { header: "سعر البيع", key: "sellPrice" },
  { header: "الكمية", key: "stock" },
];

// استيراد منتجات من Excel: رفع الملف، قراءة صفوفه، ثم إضافتها للكتالوج.
export default function ImportDialog({ open, onOpenChange, onImport }) {
  const [fileName, setFileName] = useState("");
  const [reading, setReading] = useState(false);
  const [error, setError] = useState("");
  const [parsed, setParsed] = useState([]);

  function reset() {
    setFileName("");
    setError("");
    setParsed([]);
    setReading(false);
  }

  async function handleFile(file) {
    setFileName(file.name);
    setError("");
    setParsed([]);
    setReading(true);
    try {
      const result = await readProductsFile(file);
      if (result.status !== "success") {
        setError(result.details || "تعذّر قراءة الملف. تأكد أن الأعمدة مطابقة للنموذج.");
        setReading(false);
        return;
      }
      const built = buildProductsFromRows(result.rows);
      if (built.length === 0) {
        setError("لم يتم العثور على صفوف بها اسم منتج. نزّل النموذج وطابق أسماء الأعمدة.");
        setReading(false);
        return;
      }
      setParsed(built);
      setReading(false);
    } catch (e) {
      setError("تعذّر رفع الملف أو قراءته. جرّب ملفًا أصغر أو بصيغة CSV.");
      setReading(false);
    }
  }

  function confirmImport() {
    onImport?.(parsed);
    toast.success(
      `تم استيراد ${fmtInt(parsed.length)} منتجًا و${fmtInt(parsed.reduce((s, p) => s + p.variantsCount, 0))} متغيرًا`,
    );
    reset();
    onOpenChange(false);
  }

  const totals = {
    variants: parsed.reduce((s, p) => s + p.variantsCount, 0),
    pieces: parsed.reduce((s, p) => s + p.totalStock, 0),
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent dir="rtl" className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">استيراد منتجات من Excel</DialogTitle>
          <DialogDescription>
            ارفع ملف <span className="num">xlsx</span> أو <span className="num">csv</span> يحتوي الأصناف ومتغيراتها، وسيتم إنشاء المنتجات
            والباركودات تلقائيًا. كل صف = لون + مقاس واحد.
          </DialogDescription>
        </DialogHeader>

        <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border bg-muted/30 px-4 py-4 text-center transition-colors hover:bg-muted/50">
          {reading ? <Loader2 className="h-5 w-5 animate-spin text-primary" /> : <Upload className="h-5 w-5 text-primary" />}
          <span className="text-sm font-semibold">{reading ? `جارٍ قراءة ${fileName}...` : fileName || "اسحب الملف هنا أو اضغط للاختيار"}</span>
          <span className="text-[11px] text-muted-foreground">الحد الأقصى ٥ ميجابايت • حتى ٢٠٠٠ سطر</span>
          <input
            type="file"
            accept=".xlsx,.xls,.csv"
            className="hidden"
            disabled={reading}
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (file) handleFile(file);
            }}
          />
        </label>

        {error && (
          <div className="flex items-start gap-2 rounded-lg bg-rose-50 px-3 py-2 text-[11px] text-rose-800">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {error}
          </div>
        )}

        {parsed.length > 0 && (
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-lg bg-muted/50 px-3 py-2">
                <p className="text-[11px] text-muted-foreground">منتجات جاهزة للاستيراد</p>
                <p className="num font-heading text-base font-bold">{fmtInt(parsed.length)}</p>
              </div>
              <div className="rounded-lg bg-muted/50 px-3 py-2">
                <p className="text-[11px] text-muted-foreground">متغيرات (لون + مقاس)</p>
                <p className="num font-heading text-base font-bold">{fmtInt(totals.variants)}</p>
              </div>
              <div className="rounded-lg bg-muted/50 px-3 py-2">
                <p className="text-[11px] text-muted-foreground">إجمالي القطع</p>
                <p className="num font-heading text-base font-bold">{fmtInt(totals.pieces)}</p>
              </div>
            </div>

            <div className="max-h-[30vh] overflow-y-auto scroll-slim rounded-xl border border-border">
              <table className="w-full min-w-[520px] text-sm">
                <thead className="sticky top-0 bg-muted/70 backdrop-blur">
                  <tr className="text-xs text-muted-foreground">
                    <th className="px-3 py-2 text-start font-semibold">المنتج</th>
                    <th className="px-3 py-2 text-center font-semibold">المتغيرات</th>
                    <th className="px-3 py-2 text-center font-semibold">القطع</th>
                    <th className="px-3 py-2 text-start font-semibold">سعر البيع</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {parsed.slice(0, 20).map((p) => (
                    <tr key={p.id}>
                      <td className="px-3 py-2">
                        <span className="block font-medium">{p.name}</span>
                        <span className="num block text-[11px] text-muted-foreground">
                          {p.colors.join(" • ")} — {p.sizes.join(" • ")}
                        </span>
                      </td>
                      <td className="num px-3 py-2 text-center">{fmtInt(p.variantsCount)}</td>
                      <td className="num px-3 py-2 text-center">{fmtInt(p.totalStock)}</td>
                      <td className="num px-3 py-2">{fmtMoney(p.sellPrice)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {parsed.length > 20 && <p className="num text-[11px] text-muted-foreground">معروض ٢٠ صفًا من {fmtInt(parsed.length)}</p>}
          </div>
        )}

        <div className="flex items-start gap-2 rounded-lg bg-amber-50 px-3 py-2 text-[11px] text-amber-800">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          الملف يُخزَّن بصورة خاصة ولا يُقرأ إلا عبر رابط موقّع مؤقت لاستخراج الأصناف. الباركود الناقص يُولَّد تلقائيًا.
        </div>

        <div className="flex gap-2">
          <Button
            variant="outline"
            className="flex-1 gap-2"
            onClick={() => {
              exportCsv("نموذج-استيراد-المنتجات.csv", TEMPLATE_COLUMNS, [
                { name: "تيشيرت قطن", category: "تيشيرتات", brand: "كوتون", color: "أسود", size: "L", sku: "SKU-0101-01", barcode: "2000000021010", buyPrice: 180, sellPrice: 350, stock: 10 },
                { name: "تيشيرت قطن", category: "تيشيرتات", brand: "كوتون", color: "أسود", size: "M", sku: "SKU-0101-02", barcode: "2000000021011", buyPrice: 180, sellPrice: 350, stock: 8 },
              ]);
              toast.success("تم تنزيل نموذج الأعمدة");
            }}
          >
            <FileSpreadsheet className="h-4 w-4" />
            نموذج الأعمدة
          </Button>
          <Button className="flex-1 gap-2 font-bold" disabled={parsed.length === 0 || reading} onClick={confirmImport}>
            استيراد {parsed.length > 0 ? `${fmtInt(parsed.length)} منتجًا` : ""}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}