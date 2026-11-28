import { useRef, useState } from "react";
import { FolderArchive, Loader2 } from "lucide-react";
import SectionCard from "@/applications/apparel/components/ui-kit/SectionCard";
import { reportLines, reportTone, zipFileProblem } from "@/applications/apparel/lib/imageZipReport";

const TONE = {
  good: "border-[#cfe6d3] bg-[#f0f8f1] text-[#256b36]",
  partial: "border-[#f2ddb6] bg-[#fdf3e4] text-[#96631a]",
  bad: "border-[#f4cfcb] bg-[#fdf0ee] text-[#a52a1c]",
};

// صور المجموعة في ملف مضغوط واحد: اسم الملف = SKU. التقرير بيقول اللي اتربط واللي ماوصلش.
export default function ImageZipCard({ busy, error, onUpload }) {
  const input = useRef(null);
  const [local, setLocal] = useState("");
  const [report, setReport] = useState(null);
  const [name, setName] = useState("");

  async function take(file) {
    setLocal("");
    setReport(null);
    const problem = zipFileProblem(file);
    setLocal(problem ?? "");
    if (problem) return;
    setName(file.name);
    const result = await onUpload(file);
    if (result) setReport(result);
  }

  const message = local || error;
  const lines = reportLines(report);

  return (
    <SectionCard
      title="صور المنتجات في ملف مضغوط"
      description="سمّي كل صورة بالـSKU (TEE-BK-M.jpg)، ولو فيه زاوية تانية ضيف -2 أو (1). حتى 10 صور للصنف"
    >
      <input
        ref={input}
        type="file"
        accept=".zip,application/zip"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file) take(file);
        }}
      />
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => !busy && input.current?.click()}
          disabled={busy}
          className="inline-flex h-11 items-center gap-2 rounded-xl border border-[#d9d4cd] bg-white px-4 text-[13px] font-semibold text-[#3a342d] transition-colors hover:border-[#E8761A] hover:text-[#E8761A] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <FolderArchive className="h-4 w-4" />}
          {busy ? "جاري رفع الصور…" : "اختر ملف الصور (.zip)"}
        </button>
        {name && !busy && <span className="text-[12px] text-[#8a8277]">{name}</span>}
      </div>

      {message && <p className="mt-3 text-[12px] font-semibold text-[#B42318]">{message}</p>}

      {report && (
        <ul
          className={`mt-3 flex flex-col gap-1 rounded-xl border px-3 py-2 text-[12px] ${TONE[reportTone(report)]}`}
        >
          {lines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
    </SectionCard>
  );
}
