import { useRef, useState } from "react";
import { AlertTriangle, FileArchive, Loader2 } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import SectionCard from "@/cashier/components/ui-kit/SectionCard";
import { archiveFileProblem, archiveSummary, refusedText } from "@/cashier/api/importCenter";

/**
 * Optional step: the pictures themselves, as one .zip. The Images sheet can name a file ("tee-red.jpg")
 * instead of giving a link, and this is where that file comes from. Shown only when the workbook has an
 * Images sheet, so a merchant who has no pictures never sees it.
 */
export default function ImageArchiveCard({ session, busy, error, onFile }) {
  const input = useRef(null);
  const [local, setLocal] = useState("");
  const summary = archiveSummary(session.stats);

  function take(file) {
    const problem = archiveFileProblem(file);
    setLocal(problem ?? "");
    if (!problem) onFile(file);
  }

  const message = local || error;

  return (
    <SectionCard
      title="ملف صور المنتجات (اختياري)"
      description="لو كتبت في ورقة Images أسماء ملفات (مثل tee-red.jpg) ارفع هنا ملف zip فيه الصور. الروابط لا تحتاج ملفًا."
    >
      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => input.current?.click()}>
          {busy ? <Loader2 className="me-1 h-4 w-4 animate-spin" aria-hidden="true" /> : <FileArchive className="me-1 h-4 w-4" aria-hidden="true" />}
          {summary ? "استبدال ملف الصور" : "اختيار ملف zip"}
        </Button>
        <span className="text-[12px] text-muted-foreground">حتى 200 ميجابايت. كل صورة حتى 10 ميجابايت (JPG أو PNG أو GIF أو WebP أو BMP).</span>
        <input
          ref={input}
          type="file"
          hidden
          accept=".zip,application/zip,application/x-zip-compressed"
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = ""; // the same file can be picked again after a fix
            take(file);
          }}
        />
      </div>

      {summary && (
        <div className="mt-3 rounded-lg bg-[#F4F1EC] px-3 py-2.5 text-[12px] leading-relaxed text-[#5C5850]" data-testid="archive-summary">
          تم رفع ملف الصور: <b>{summary.files}</b> صورة ({summary.megabytes} ميجابايت). أعد «فحص الملف» ليُطابَق مع أسماء الورقة.
        </div>
      )}

      {summary?.ambiguous.length > 0 && (
        <p role="alert" className="mt-2 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-800">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span>صور مختلفة بنفس الاسم داخل الملف، ولن تُستخدم: {summary.ambiguous.join("، ")}</span>
        </p>
      )}

      {summary?.refused.length > 0 && (
        <details className="mt-2 text-[12px]">
          <summary className="cursor-pointer text-amber-800">{summary.refused.length} ملف داخل zip تم تجاهله</summary>
          <ul className="mt-1 list-disc ps-5 text-[#7A766C]">
            {summary.refused.map((r) => (
              <li key={r.name} dir="ltr" className="text-start">
                {r.name} <span dir="rtl">({refusedText(r.reason)})</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      {message && (
        <p role="alert" className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700">
          {message}
        </p>
      )}
    </SectionCard>
  );
}
