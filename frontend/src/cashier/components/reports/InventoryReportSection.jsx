import ReportTable from "@/cashier/components/reports/ReportTable";
import { CELL_MAIN, CELL_NUM } from "@/cashier/components/ui-kit/ledgerStyles";
import { summarizeValuation } from "@/cashier/api/inventoryValuation";
import { fmtInt, fmtMoney } from "@/cashier/lib/format";

const margin = (m) => (m === null || m === undefined ? "—" : `${m}%`);

// تقرير تقييم المخزون: قيمة الأرصدة الحالية بتكلفتها (متوسط متحرك) وبسعر بيعها، من نفس صفوف شاشة المخزون.
// التكلفة المجهولة لا تُحسب صفرًا: تظهر كعدد أصناف ناقصة، ويُحسب الهامش على الأصناف المعروفة التكلفة فقط.
export default function InventoryReportSection({ rows }) {
  const sum = summarizeValuation(rows);

  const columns = [
    { key: "category", header: "التصنيف", render: (r) => <span className={`${CELL_MAIN} font-semibold`}>{r.category}</span> },
    { key: "items", header: "عدد الأصناف", align: "center", render: (r) => <span className={CELL_NUM}>{fmtInt(r.items)}</span> },
    { key: "variants", header: "لون / مقاس", align: "center", render: (r) => <span className={CELL_NUM}>{fmtInt(r.variants)}</span> },
    { key: "pieces", header: "القطع المتوفرة", align: "center", render: (r) => <span className={CELL_NUM}>{fmtInt(r.pieces)}</span> },
    { key: "cost", header: "قيمة التكلفة", align: "end", render: (r) => <span className={`${CELL_NUM} text-[#7A766C]`}>{fmtMoney(r.cost)}</span> },
    { key: "unknown", header: "تكلفة مجهولة", align: "center", render: (r) => <span className={`${CELL_NUM} ${r.unknownCost ? "font-semibold text-amber-600" : "text-[#7A766C]"}`}>{r.unknownCost ? fmtInt(r.unknownCost) : "—"}</span> },
    { key: "retail", header: "قيمة البيع المتوقعة", align: "end", render: (r) => <span className={`${CELL_NUM} font-semibold`}>{fmtMoney(r.retail)}</span> },
    { key: "margin", header: "هامش الربح", align: "center", render: (r) => <span className={CELL_NUM}>{margin(r.margin)}</span> },
  ];

  const totals = {
    category: "الإجمالي",
    items: fmtInt(sum.items),
    variants: fmtInt(sum.variants),
    pieces: fmtInt(sum.pieces),
    cost: fmtMoney(sum.cost),
    unknown: sum.unknownCost ? fmtInt(sum.unknownCost) : "—",
    retail: fmtMoney(sum.retail),
    margin: margin(sum.margin),
  };

  const notes = [];
  if (sum.unknownCost) notes.push(`عدد الأصناف بلا تكلفة مسجّلة: ${fmtInt(sum.unknownCost)}. لم تُحسب في قيمة التكلفة ولا في الهامش (تظهر التكلفة بعد أول فاتورة شراء).`);
  if (sum.truncated) notes.push("عدد الأصناف وصل حد التحميل، فقد تكون الإجماليات ناقصة.");

  return (
    <ReportTable
      title="تقييم المخزون"
      description="قيمة الأرصدة المتوفرة حاليًا بالتكلفة وبسعر البيع (لحظة فتح التقرير، لا تتبع فلتر الفترة)"
      columns={columns}
      rows={rows}
      totals={totals}
      footnote={notes.length ? notes.join(" ") : undefined}
    />
  );
}
