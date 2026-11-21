/**
 * What the season-markdown dialog says and draws, as plain data, so each rule is tested by calling it.
 *
 * The rule that matters: a size that would sell UNDER what the shop paid is shown in red BEFORE the
 * owner confirms, with the count in the sentence above the table. It is shown, not blocked: clearing
 * a season below cost is the owner's call. A size with no booked cost is never called "under cost".
 */
import { fmtInt } from "@/cashier/lib/format";
import { moneyCell, variantLabel } from "@/cashier/components/reports/profitView";

/** Old price, an arrow, new price: the one cell the owner reads. */
export function priceChange(row) {
  return `${moneyCell(row?.oldPrice)} ← ${moneyCell(row?.newPrice)}`;
}

/** The tone of a row: red when it would sell under cost, muted otherwise. */
export const rowTone = (row) => (row?.belowCost ? "loss" : "");

export function markdownColumns() {
  return [
    {
      key: "variant",
      header: "الصنف",
      tone: () => "main",
      text: (r) => variantLabel(r).title,
      sub: (r) => variantLabel(r).detail,
    },
    { key: "old", header: "السعر الحالي", align: "end", tone: () => "muted", text: (r) => moneyCell(r.oldPrice) },
    { key: "new", header: "بعد التخفيض", align: "end", tone: (r) => (r.belowCost ? "loss" : "strong"), text: (r) => moneyCell(r.newPrice) },
    {
      key: "cost",
      header: "تكلفة الشراء",
      align: "end",
      tone: () => "muted",
      // An unknown cost is a dash, never 0.00.
      text: (r) => (r.costKnown && r.unitCost !== null && r.unitCost !== undefined ? moneyCell(r.unitCost) : "—"),
    },
    {
      key: "flag",
      header: "",
      align: "center",
      tone: (r) => (r.belowCost ? "loss" : "muted"),
      text: (r) => (r.belowCost ? "تحت التكلفة" : r.atFloor ? "أقل سعر" : ""),
    },
  ];
}

/** The sentence above the table: how many sizes and products, and the red count when there is one. */
export function previewSummary(totals) {
  if (!totals || !Number(totals.variants)) return "";
  const parts = [`${fmtInt(totals.variants)} مقاس من ${fmtInt(totals.products)} موديل هيتغيّر سعرهم`];
  if (Number(totals.belowCost) > 0) parts.push(`${fmtInt(totals.belowCost)} منهم هيتباع بأقل من التكلفة`);
  return parts.join(" • ");
}

/** The warning the owner must read before confirming, or null when nothing goes under cost. */
export function belowCostWarning(totals) {
  const n = Number(totals?.belowCost) || 0;
  if (n === 0) return null;
  return `تنبيه: ${fmtInt(n)} مقاس هيتباع بأقل من تكلفة الشراء بعد التخفيض (باللون الأحمر). التخفيض مش هيتمنع، لكن راجعهم قبل ما تأكد.`;
}

/** A softer note when some sizes have no booked cost, so "not under cost" is not mistaken for "safe". */
export function unknownCostNote(totals) {
  const n = Number(totals?.withoutCost) || 0;
  if (n === 0) return null;
  return `${fmtInt(n)} مقاس ما له تكلفة شراء مسجّلة، فمش قادرين نقول لو هيتباع بخسارة.`;
}

/** The note about sizes held at the lowest possible price. */
export function floorNote(totals) {
  const n = Number(totals?.atFloor) || 0;
  if (n === 0) return null;
  return `${fmtInt(n)} مقاس وصل لأقل سعر ممكن، فاتثبّت عنده.`;
}

/** The confirm button's label: it names what will happen so the owner is not confirming blind. */
export function confirmLabel(preview) {
  const n = Number(preview?.totals?.variants) || 0;
  return n > 0 ? `تأكيد التخفيض على ${fmtInt(n)} مقاس` : "تأكيد";
}

/** Can Preview be pressed? Needs a season and a percent that is valid. */
export function canPreview({ season, percentValid, busy }) {
  return !busy && String(season ?? "").trim().length > 0 && !!percentValid;
}

/** Can Confirm be pressed? Needs a preview that found something, with its token, and nothing running. */
export function canConfirm({ preview, busy }) {
  return !busy && !!preview?.token && Number(preview?.totals?.variants) > 0;
}

/** The message for each way a request can fail; "stale" asks for a NEW preview, not a retry. */
export function markdownErrorMessage(kind) {
  switch (kind) {
    case "stale":
      return "الأسعار اتغيّرت من وقت المعاينة، أو مفيش مقاسات للموسم ده. اعمل معاينة جديدة وراجعها قبل التأكيد.";
    case "forbidden":
      return "تخفيض الموسم لصاحب المحل أو المدير بس. اطلب من المدير ينفّذه.";
    case "invalid":
      return "النسبة لازم تكون من 0.01 لـ90 وبحد أقصى رقمين بعد العلامة، واسم الموسم مطلوب.";
    case "offline":
      return "تعذّر الوصول للخادم. اتأكد من الاتصال وحاول مرة أخرى.";
    default:
      return "تعذّر تنفيذ التخفيض. حاول مرة أخرى.";
  }
}

/** The message after a successful apply. */
export function appliedMessage(result) {
  const n = Number(result?.applied) || 0;
  return `اتخفّض سعر ${fmtInt(n)} مقاس.`;
}
