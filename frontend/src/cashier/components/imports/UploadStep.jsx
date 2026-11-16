import { useRef, useState } from "react";
import { Download, FileSpreadsheet, Loader2, UploadCloud } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import SectionCard from "@/cashier/components/ui-kit/SectionCard";
import { downloadTemplate, importFileProblem } from "@/cashier/api/importCenter";
import { cn } from "@/cashier/lib/utils";

/** Step 1: pick a file. The first thing the merchant sees, so it also says what the file may hold. */
export default function UploadStep({ busy, error, onFile }) {
  const input = useRef(null);
  const [over, setOver] = useState(false);
  const [local, setLocal] = useState("");
  const [fetching, setFetching] = useState(false);
  const [templateError, setTemplateError] = useState("");

  async function getTemplate() {
    setFetching(true);
    setTemplateError("");
    try {
      await downloadTemplate();
    } catch {
      setTemplateError("تعذّر تنزيل القالب. حاول مرة أخرى.");
    } finally {
      setFetching(false);
    }
  }

  function take(file) {
    const problem = importFileProblem(file);
    setLocal(problem ?? "");
    if (!problem) onFile(file);
  }

  const message = local || error;

  return (
    <SectionCard title="ارفع ملف المنتجات" description="Excel (.xlsx) أو CSV، حتى 20 ميجابايت">
      <div
        role="button"
        tabIndex={0}
        aria-label="اختر ملفًا أو اسحبه هنا"
        onClick={() => !busy && input.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && !busy && input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          if (!busy) take(e.dataTransfer.files?.[0]);
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors",
          over ? "border-[#E8761A] bg-[#FDF3EA]" : "border-[#C7C2B8] bg-[#FBFAF7] hover:border-[#E8761A]",
          busy && "pointer-events-none opacity-70",
        )}
      >
        {busy ? <Loader2 className="h-8 w-8 animate-spin text-[#E8761A]" aria-hidden="true" /> : <UploadCloud className="h-8 w-8 text-[#E8761A]" aria-hidden="true" />}
        <p className="font-heading text-[14px] font-semibold">{busy ? "جارٍ رفع الملف وقراءته…" : "اسحب الملف هنا أو اضغط للاختيار"}</p>
        <p className="max-w-md text-[12px] leading-relaxed text-muted-foreground">
          الملف يمكن أن يحتوي على ورقة <b>المنتجات</b> وورقة <b>الأصناف</b> (اللون والمقاس) وورقة <b>رصيد أول المدة</b>. ملف CSV يُقرأ كقائمة منتجات.
        </p>
        <input
          ref={input}
          type="file"
          hidden
          accept=".xlsx,.csv,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = ""; // the same file can be picked again after a fix
            take(file);
          }}
        />
      </div>

      {message && (
        <p role="alert" className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700">
          {message}
        </p>
      )}

      <div className="mt-4 flex items-start gap-2 rounded-lg bg-[#F4F1EC] px-3 py-2.5 text-[12px] leading-relaxed text-[#7A766C]">
        <FileSpreadsheet className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <span>
          لن يتغيّر شيء في متجرك قبل أن تراجع النتيجة وتضغط «ابدأ الاستيراد». الأعمدة تُربط تلقائيًا ويمكنك تعديلها في الخطوة التالية.
          <Button type="button" variant="link" className="h-auto p-0 ps-1 text-[12px]" onClick={() => input.current?.click()} disabled={busy}>
            اختيار ملف
          </Button>
        </span>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-[12px] text-[#7A766C]">
        <Button type="button" variant="outline" size="sm" onClick={getTemplate} disabled={busy || fetching}>
          {fetching ? <Loader2 className="me-1 h-4 w-4 animate-spin" aria-hidden="true" /> : <Download className="me-1 h-4 w-4" aria-hidden="true" />}
          تنزيل قالب Excel جاهز
        </Button>
        <span>أوراق المنتجات والأصناف ورصيد أول المدة بعناوين تُربط تلقائيًا. الأعمدة المطلوبة بلون مختلف.</span>
      </div>
      {templateError && <p role="alert" className="mt-2 text-[12px] text-red-700">{templateError}</p>}
    </SectionCard>
  );
}
