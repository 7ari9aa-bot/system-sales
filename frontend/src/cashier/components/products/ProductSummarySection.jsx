import FormField from "@/cashier/components/products/FormField";
import { DOT, GRID2, READONLY, SECTION, SECTION_HEAD, SECTION_HINT, SECTION_TITLE } from "@/cashier/components/products/formStyles";
import { fmtInt } from "@/cashier/lib/format";

// ملخص سريع يُحدَّث من جدول التركيبات.
export default function ProductSummarySection({ rows }) {
  const pieces = rows.reduce((sum, row) => sum + row.stock, 0);

  return (
    <div className={SECTION}>
      <div className={SECTION_HEAD}>
        <span className={DOT} />
        <h2 className={SECTION_TITLE}>ملخص المخزون</h2>
        <span className={SECTION_HINT}>يُحدَّث تلقائياً من جدول التركيبات</span>
      </div>

      <div className={GRID2}>
        <FormField label="عدد التركيبات">
          <div className={READONLY}>{fmtInt(rows.length)}</div>
        </FormField>
        <FormField label="إجمالي الرصيد الافتتاحي">
          <div className={READONLY}>
            {fmtInt(pieces)} <span className="ms-1 text-xs font-normal text-[#8a8277]">قطعة</span>
          </div>
        </FormField>
      </div>
    </div>
  );
}