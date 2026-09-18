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

/** تنسيق مبلغ مالي مع العملة — الأرقام دائمًا LTR داخل RTL. */
export function formatMoney(value: number | string, currency = "EGP") {
  return `${Number(value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
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
