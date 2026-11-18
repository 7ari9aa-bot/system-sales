// اختيار سبب المرتجع من القائمة التي ضبطها صاحب المحل. اختياري، ويُسجَّل على كل قطعة مرتجعة.
// لا تظهر القائمة إذا لم يحدد المحل أسبابًا، فلا نعرض اختيارًا فارغًا.
const LABELS = {
  size: "المقاس",
  defect: "عيب في القطعة",
  changed_mind: "غيّر العميل رأيه",
  wrong_item: "قطعة خطأ",
};

export const reasonLabel = (r) => LABELS[r] ?? r;

export default function ReturnReasonSelect({ reasons, value, onChange }) {
  if (!reasons?.length) return null;
  return (
    <label className="flex items-center gap-2 text-[12px] font-semibold text-foreground/80">
      سبب المرتجع
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        className="h-8 rounded-md border border-border bg-background px-2 text-[12px]"
      >
        <option value="">بدون سبب</option>
        {reasons.map((r) => (
          <option key={r} value={r}>
            {reasonLabel(r)}
          </option>
        ))}
      </select>
    </label>
  );
}
