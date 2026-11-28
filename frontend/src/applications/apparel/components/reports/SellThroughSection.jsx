import ReportTable from "@/applications/apparel/components/reports/ReportTable";
import { toneClass } from "@/applications/apparel/components/reports/ProfitReportSection";
import {
  sellThroughColumns,
  sellThroughSummary,
  sellThroughTotalsRow,
} from "@/applications/apparel/components/reports/sellThroughView";

const SUB = "mt-0.5 block text-[11px] text-[#7A766C]";
const BAR_TRACK = "mt-1 block h-1.5 w-full min-w-[56px] bg-[#EFEBE3]";
const BAR_FILL = "block h-full bg-[#33322E]";

/**
 * التصريف حسب الموديل واللون والمقاس: اتباع كام وفاضل كام ونسبة اللي اتباع، الأعلى نسبة الأول، فالمقاس
 * اللي قرّب يخلص يبان فوق والمقاس الراكد يبان تحت. الأرقام كلها من الخادم، وأرقام المبيعات نفسها بتاعة
 * تقرير الربح فمفيش رقمين مختلفين لنفس الفترة.
 */
export default function SellThroughSection({ rows = [], totals = null }) {
  const list = rows ?? [];
  const columns = sellThroughColumns().map((c) => ({
    key: c.key,
    header: c.header,
    align: c.align,
    render: (r) => (
      <span className={toneClass(c.tone(r))}>
        {c.text(r)}
        {c.sub && c.sub(r) && <span className={SUB}>{c.sub(r)}</span>}
        {c.bar && (
          <span className={BAR_TRACK} aria-hidden="true">
            <span className={BAR_FILL} style={{ width: `${c.bar(r)}%` }} />
          </span>
        )}
      </span>
    ),
  }));
  const summary = sellThroughSummary(list);

  if (list.length === 0) {
    return (
      <div className="border border-[#DED8CD] bg-white">
        <div className="border-b border-[#DED8CD] px-3.5 py-2">
          <h2 className="font-heading text-[13px] font-bold text-[#33322E]">التصريف حسب الصنف</h2>
        </div>
        <p className="px-3.5 py-10 text-center text-[12px] text-[#7A766C]" role="status">
          مفيش مبيعات ولا رصيد في الفترة دي بالفلتر المختار. جرّب فترة أطول أو شيل فلتر العلامة أو الموسم أو الخامة.
        </p>
      </div>
    );
  }

  return (
    <ReportTable
      title="التصريف حسب الصنف"
      description={summary || "اتباع كام وفاضل كام من كل موديل ولون ومقاس، الأعلى نسبة الأول"}
      columns={columns}
      rows={list}
      totals={sellThroughTotalsRow(totals)}
      footnote="النسبة = ما بيع ÷ (ما بيع + المتبقي)، والمبيعات بعد المرتجعات كما في تقرير الربح."
    />
  );
}
