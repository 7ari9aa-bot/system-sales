import { Delete, X } from "lucide-react";

/** لوحة أرقام الكاشير — لمس، للحقول المختارة (نموذج «اختار الحقل واكتب»).
 *
 * الزراير بتبعت أحداث للأب؛ الأب هو اللي يقرر الحقل النشط. النقطة والجزء
 * العشري بيتظبطوا في الأب (مونيز 2). */
const DIGITS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0"];

export default function Numpad({ onDigit, onBackspace, onClear, disabled }) {
  const btn =
    "h-11 rounded-xl border border-border bg-surface text-[15px] font-medium tabular-nums hover:bg-muted disabled:opacity-40";
  return (
    <div className="grid grid-cols-4 gap-1.5" dir="ltr">
      {DIGITS.map((d) => (
        <button
          key={d}
          type="button"
          disabled={disabled}
          onClick={() => onDigit(d)}
          className={btn}
        >
          {d}
        </button>
      ))}
      <button type="button" disabled={disabled} onClick={onBackspace} className={btn} aria-label="Backspace">
        <Delete className="mx-auto h-4 w-4" />
      </button>
      <button type="button" disabled={disabled} onClick={onClear} className={btn} aria-label="Clear">
        <X className="mx-auto h-4 w-4" />
      </button>
    </div>
  );
}
