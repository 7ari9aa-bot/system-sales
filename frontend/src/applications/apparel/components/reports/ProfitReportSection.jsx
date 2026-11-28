import ReportTable from "@/applications/apparel/components/reports/ReportTable";
import {
  costWarning,
  profitColumns,
  returnCostNotice,
  profitFootnote,
  profitTotalsRow,
} from "@/applications/apparel/components/reports/profitView";

// الأنماط اللي بتفرّق الصف عن الصف: العنوان الأساسي، السطر اللي تحته، والرقم.
// "loss" هو الأحمر الوحيد في الجدول: خسارة لازم تبان خسارة، مش رقم عادي.
const TONE = {
  main: "block text-[12px] font-semibold text-[#33322E]",
  strong: "num text-[12px] font-semibold text-[#33322E]",
  muted: "num text-[12px] text-[#7A766C]",
  loss: "num text-[12px] font-semibold text-rose-600",
  "": "num text-[12px]",
};
const SUB = "mt-0.5 block text-[11px] text-[#7A766C]";
const MARK = "ms-1 text-[10px] text-[#7A766C]";

/** The classes for a cell, so a loss and a profit never share a colour. */
export const toneClass = (tone) => TONE[tone] ?? TONE[""];

/**
 * الربح حسب الموديل واللون والمقاس من دفاتر المحل نفسها: الإيراد بعد الخصومات والمرتجعات،
 * والتكلفة من شرائح الشراء الفعلية. الرقم اللي الدفاتر مش قادرة تقوله بيُقال صريحًا:
 * قطعة اتباعت من غير تكلفة مسجّلة بترفع الربح، فبيظهر تحذير بعددها بدل ما الرقم يعدّي.
 */
export default function ProfitReportSection({ rows = [], totals = null }) {
  const list = rows ?? [];
  const columns = profitColumns().map((c) => ({
    key: c.key,
    header: c.header,
    align: c.align,
    render: (r) => (
      <span className={toneClass(c.tone(r))}>
        {c.text(r)}
        {c.sub && c.sub(r) && <span className={SUB}>{c.sub(r)}</span>}
        {c.mark && c.mark(r) && <span className={MARK}>{c.mark(r)}</span>}
      </span>
    ),
  }));

  const warning = costWarning(totals, list);
  const estimated = returnCostNotice(totals);

  return (
    <div>
      {warning && (
        <p
          className="border border-amber-300 bg-amber-50 px-3.5 py-2.5 text-[11.5px] font-medium text-amber-800"
          role="alert"
        >
          {warning}
        </p>
      )}
      {estimated && (
        <p className="mt-2 border border-slate-300 bg-slate-50 px-3.5 py-2.5 text-[11.5px] font-medium text-slate-700">
          {estimated}
        </p>
      )}
      {list.length === 0 ? (
        // حالة فاضية أمينة: بتقول إن مفيش بيع في الفترة/الفلتر ده، مش بتعرض صفوف صفراء توهم برقم.
        <div className="border border-[#DED8CD] bg-white">
          <div className="border-b border-[#DED8CD] px-3.5 py-2">
            <h2 className="font-heading text-[13px] font-bold text-[#33322E]">الربح حسب الصنف</h2>
          </div>
          <p className="px-3.5 py-10 text-center text-[12px] text-[#7A766C]" role="status">
            مفيش مبيعات في الفترة دي بالفلتر المختار، فمفيش ربح يتحسب. جرّب فترة أطول أو شيل فلتر العلامة أو الموسم.
          </p>
        </div>
      ) : (
        <ReportTable
          title="الربح حسب الصنف"
          description="إيراد وتكلفة وربح كل موديل ولون ومقاس في الفترة، الأعلى ربحًا الأول"
          columns={columns}
          rows={list}
          totals={profitTotalsRow(totals)}
          footnote={profitFootnote(totals, list) || undefined}
        />
      )}
    </div>
  );
}
