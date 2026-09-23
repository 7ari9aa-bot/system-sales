import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** دمج أصناف Tailwind مع إزالة التعارضات (shadcn convention). */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** تنسيق الأرقام بأرقام لاتينية داخل واجهة عربية (متسق مع بقية الشاشات). */
export function formatNumber(value: number, opts: Intl.NumberFormatOptions = {}) {
  return value.toLocaleString("en-US", opts);
}

/** تنسيق مبلغ مالي مع العملة — الأرقام دائمًا LTR داخل RTL.
 *
 *  §47: money arrives from the backend as a Decimal STRING (`"250.00"`). The
 *  old version ran every amount through `Number(...)` — a float64 — and cents
 *  started disappearing above 2^53 (or with three-decimal drift). This formats
 *  the integer/fraction parts as strings and never coerces the amount. The
 *  currency is a parameter, not a literal: the caller reads it from the row
 *  (`grand_total`/`currency`) or from `useTenantCurrency` (item C) so a UI
 *  surface never invents a symbol.
 */
export function formatMoney(value: number | string | null | undefined, currency?: string | null) {
  if (value === null || value === undefined || value === "") return "—";
  const raw = typeof value === "number" ? finiteOrDash(value) : String(value).trim();
  if (raw === "—") return raw;
  const neg = raw.startsWith("-");
  const body = neg ? raw.slice(1) : raw;
  const [int, frac = ""] = body.split(".");
  if (!/^\d*$/.test(int) || !/^\d*$/.test(frac)) return "—";
  const grouped = (int || "0").replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const cents = (frac + "00").slice(0, 2);
  const code = currency?.trim();
  return `${neg ? "-" : ""}${grouped}.${cents}${code ? ` ${code}` : ""}`;
}

function finiteOrDash(n: number): string {
  if (!Number.isFinite(n)) return "—";
  // Numbers here come from JSON, so at most 17 sig digits; `toFixed` would
  // re-enter float math. Render via the shortest round-trip string instead.
  return String(n);
}

/** تنسيق تاريخ قصير. */
export function formatDate(iso: string | null | undefined) {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("ar-EG-u-nu-latn", { dateStyle: "medium" }).format(new Date(iso));
}

/** تنسيق وقت قصير (ساعة:دقيقة). */
export function formatTime(iso: string | null | undefined) {
  if (!iso) return "";
  return new Intl.DateTimeFormat("ar-EG-u-nu-latn", { hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}
