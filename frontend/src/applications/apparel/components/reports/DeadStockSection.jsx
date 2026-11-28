import ReportTable from "@/applications/apparel/components/reports/ReportTable";
import { toneClass } from "@/applications/apparel/components/reports/ProfitReportSection";
import {
  costGapWarning,
  deadStockColumns,
  deadStockHeader,
  deadStockTotalsRow,
} from "@/applications/apparel/components/reports/deadStockView";

const SUB = "mt-0.5 block text-[11px] text-[#7A766C]";

/**
 * المخزون الراكد: مقاسات فيها رصيد وما اتباعتش المدة اللي صاحب المتجر حدّدها. القيمة بالتكلفة،
 * والتكلفة المجهولة بتظهر شرطة وتحذير، مش صفر: مقاس مش عارفين تكلفته هو بالظبط اللي صاحب المتجر
 * محتاج ينتبه له.
 */
export default function DeadStockSection({ days = null, rows = [], totals = null }) {
  const list = rows ?? [];
  const columns = deadStockColumns().map((c) => ({
    key: c.key,
    header: c.header,
    align: c.align,
    render: (r) => (
      <span className={toneClass(c.tone(r))}>
        {c.text(r)}
        {c.sub && c.sub(r) && <span className={SUB}>{c.sub(r)}</span>}
      </span>
    ),
  }));
  const warning = costGapWarning(totals);
  const header = deadStockHeader(days);

  return (
    <div>
      {warning && list.length > 0 && (
        <p
          className="border border-amber-300 bg-amber-50 px-3.5 py-2.5 text-[11.5px] font-medium text-amber-800"
          role="alert"
        >
          {warning}
        </p>
      )}
      {list.length === 0 ? (
        <div className="border border-[#DED8CD] bg-white">
          <div className="border-b border-[#DED8CD] px-3.5 py-2">
            <h2 className="font-heading text-[13px] font-bold text-[#33322E]">المخزون الراكد</h2>
          </div>
          <p className="px-3.5 py-10 text-center text-[12px] text-[#7A766C]" role="status">
            {days
              ? `لا يوجد مقاس له رصيد ولم يُبع منذ ${days} يوماً. وهذه المدة من إعدادات المتجر.`
              : "لا يوجد مخزون راكد حالياً."}
          </p>
        </div>
      ) : (
        <ReportTable
          title="المخزون الراكد"
          description={header || "مقاسات فيها رصيد وما اتباعتش من فترة"}
          columns={columns}
          rows={list}
          totals={deadStockTotalsRow(totals)}
          footnote="المدة من إعدادات المتجر، والقيمة بسعر الشراء. وما لم يُبع قط يُحتسب من أول مرة دخل المخزن."
        />
      )}
    </div>
  );
}
