// Manual drawer movements for the open shift. The backend ledger is append-only and
// knows four reasons; the cashier thinks in three plain words. This file is the one
// place that maps between them and refuses bad input BEFORE any request is made.
import { fromMinor, toMinor } from "./money";

export const MOVEMENT_KINDS = [
  { kind: "pay_in", label: "إيداع في الخزنة", direction: "in", hint: "نقدية دخلت الدرج (مثل فكّة من الإدارة)" },
  { kind: "pay_out", label: "مصروف من الخزنة", direction: "out", hint: "نقدية خرجت لدفع مصروف" },
  { kind: "cash_drop", label: "سحب إلى الخزنة الرئيسية", direction: "out", hint: "تخفيف النقدية الزائدة من الدرج" },
];

const ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩";

/** "٥٠٫٥" / "50,5" / " 50.50 " -> "50.5" (what toMinor understands). */
export function normalizeAmountText(raw) {
  return String(raw ?? "")
    .trim()
    .replace(/[٠-٩]/g, (d) => String(ARABIC_DIGITS.indexOf(d)))
    .replace(/[٫,]/g, ".");
}

export function planMovement({ kind, amount, expectedCash }) {
  const def = MOVEMENT_KINDS.find((k) => k.kind === kind);
  if (!def) return { ok: false, error: "اختر نوع الحركة." };
  let cents;
  try {
    cents = toMinor(normalizeAmountText(amount));
  } catch {
    return { ok: false, error: "اكتب مبلغًا صحيحًا." };
  }
  if (cents <= 0) return { ok: false, error: "المبلغ يجب أن يكون أكبر من صفر." };
  if (def.direction === "out" && expectedCash != null) {
    let have;
    try {
      have = toMinor(expectedCash);
    } catch {
      have = null; // unknown balance: let the backend be the judge
    }
    if (have != null && cents > have) return { ok: false, error: "المبلغ أكبر من النقدية المتوقعة في الدرج." };
  }
  return { ok: true, direction: def.direction, reason: def.kind, amount: fromMinor(cents) };
}
