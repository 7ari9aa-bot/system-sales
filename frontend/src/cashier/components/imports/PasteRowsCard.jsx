import { useMemo, useState } from "react";
import { ClipboardPaste, Loader2 } from "lucide-react";
import SectionCard from "@/cashier/components/ui-kit/SectionCard";
import { previewPaste } from "@/cashier/lib/pastePreview";

// اللصق المباشر: التاجر بياخد خلاياه من Excel ويلزقها هنا. المعاينة فورية (أعمدة مفهومة، سعر مش
// رقم، SKU مكرر) وبعدها الصفوف بتبقى جلسة استيراد عادية — نفس المراجعة والتحقق والتنفيذ.
export default function PasteRowsCard({ busy, error, onPaste }) {
  const [text, setText] = useState("");
  const [local, setLocal] = useState("");
  const preview = useMemo(() => previewPaste(text), [text]);
  const message = local || error;

  function submit() {
    setLocal("");
    if (!preview.ready) {
      setLocal(preview.problems[0]?.message ?? "الصق الصفوف الأول");
      return;
    }
    if (preview.problems.length) {
      setLocal(`فيه ${preview.problems.length} مشكلة في اللصق. صلّحها أو ارفع الملف لو الأسهل.`);
      return;
    }
    onPaste(text);
  }

  return (
    <SectionCard
      title="أو الصق الصفوف من Excel"
      description="انسخ الخلايا مع سطر العناوين والصقها هنا: اسم المنتج، المقاس، اللون، السعر، SKU، الكمية"
    >
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={5}
        spellCheck={false}
        aria-label="الصق صفوف المنتجات"
        placeholder={"اسم المنتج\tالمقاس\tاللون\tالسعر\tSKU\tالكمية\nتيشيرت قطن\tM\tأسود\t250\tTEE-M\t4"}
        className="w-full resize-y rounded-xl border border-[#ddd7cf] bg-[#faf9f7] px-3 py-2 font-mono text-[12px] leading-6 text-[#2a2622] outline-none transition-[border-color,box-shadow] focus:border-[#E8761A] focus:shadow-[0_0_0_3px_rgba(232,118,26,.15)]"
      />

      {preview.rows.length > 0 && (
        <div className="mt-3 overflow-hidden rounded-xl border border-[#eee9e2]">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#eee9e2] bg-[#faf9f7] px-3 py-2 text-[12px] text-[#6b6358]">
            <span>
              {preview.rows.length} سطر · {preview.productCount} منتج ·{" "}
              {preview.problems.length ? `${preview.problems.length} مشكلة` : "مفيش مشاكل ظاهرة"}
            </span>
            <span className="text-[#a9a29a]">الأعمدة المفهومة: {preview.columns.length}</span>
          </div>
          <div className="max-h-[220px] overflow-auto">
            <table className="w-full border-collapse text-[12px]">
              <thead className="bg-white text-[#8a8277]">
                <tr>
                  <th className="px-3 py-2 text-right font-semibold">سطر</th>
                  <th className="px-3 py-2 text-right font-semibold">المنتج</th>
                  <th className="px-3 py-2 text-right font-semibold">SKU</th>
                  <th className="px-3 py-2 text-right font-semibold">لون / مقاس</th>
                  <th className="px-3 py-2 text-right font-semibold">السعر</th>
                  <th className="px-3 py-2 text-right font-semibold">الكمية</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.slice(0, 50).map((row) => (
                  <tr key={row.line} className="border-t border-[#f2eee9]">
                    <td className="px-3 py-1.5 text-[#a9a29a]">{row.line}</td>
                    <td className="px-3 py-1.5">{row.title || "—"}</td>
                    <td className="px-3 py-1.5">{row.sku || "—"}</td>
                    <td className="px-3 py-1.5">{[row.color, row.size].filter(Boolean).join(" / ") || "—"}</td>
                    <td className="px-3 py-1.5">{row.price || "—"}</td>
                    <td className="px-3 py-1.5">{row.quantity || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {preview.problems.length > 0 && (
        <ul className="mt-3 flex flex-col gap-1 rounded-xl border border-[#f2ddb6] bg-[#fdf3e4] px-3 py-2 text-[12px] text-[#96631a]">
          {preview.problems.slice(0, 6).map((problem) => (
            <li key={`${problem.line}-${problem.message}`}>
              سطر {problem.line}: {problem.message}
            </li>
          ))}
          {preview.problems.length > 6 && <li>و{preview.problems.length - 6} مشكلة كمان…</li>}
        </ul>
      )}

      {message && <p className="mt-3 text-[12px] font-semibold text-[#B42318]">{message}</p>}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={submit}
          disabled={busy || !preview.ready}
          className="inline-flex h-11 items-center gap-2 rounded-xl border border-[#E8761A] bg-[#E8761A] px-5 text-[14px] font-bold text-white transition-colors hover:border-[#D1650F] hover:bg-[#D1650F] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ClipboardPaste className="h-4 w-4" />}
          {busy ? "جاري التحويل…" : "حوّلها لمراجعة الاستيراد"}
        </button>
        <button
          type="button"
          onClick={() => setText("")}
          className="inline-flex h-11 items-center gap-2 rounded-xl border border-[#d9d4cd] bg-white px-4 text-[13px] font-semibold text-[#3a342d] transition-colors hover:border-[#E8761A] hover:text-[#E8761A]"
        >
          مسح
        </button>
      </div>
    </SectionCard>
  );
}
