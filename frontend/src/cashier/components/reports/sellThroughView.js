/**
 * What the sell-through tab draws, as plain data: the columns, the totals row and the sentences the
 * shopkeeper acts on. No React here, so every rule is tested by calling it.
 *
 * The question this answers is "which size is running out and which one sits". So a size is read
 * three ways from its share sold: running out (most of it sold, little left), sitting (a lot left,
 * little sold), or in between. The cut-offs are display hints only and are named constants here; the
 * numbers themselves come from the server and are never recomputed.
 */
import { fmtInt } from "@/cashier/lib/format";
import { variantLabel } from "@/cashier/components/reports/profitView";

export { errorKind } from "@/cashier/components/reports/profitView";

/** At or above this share sold a size is nearly gone. */
export const RUNNING_OUT_FROM = 70;
/** At or below this share sold, with stock left, a size is sitting on the shelf. */
export const SITTING_UNTIL = 20;

/** The share as text, or a dash when there is nothing to be a share of. */
export function shareLabel(share) {
  return share === null || share === undefined ? "—" : `${Number(share).toFixed(1)}٪`;
}

/**
 * "out" (running out), "sitting", or "" for a size in between. A size with nothing left is "out"
 * only when it sold; a size with nothing sold and nothing left has no share and is neither.
 */
export function stockState(row) {
  const share = row?.share;
  if (share === null || share === undefined) return "";
  if (share >= RUNNING_OUT_FROM) return "out";
  if (share <= SITTING_UNTIL && Number(row?.unitsOnHand) > 0) return "sitting";
  return "";
}

export const STATE_TEXT = { out: "قرّب يخلص", sitting: "راكد", "": "" };

/** The bar width, clamped to 0..100 so a bad figure can never draw outside its cell. */
export function barWidth(share) {
  if (share === null || share === undefined) return 0;
  return Math.max(0, Math.min(100, Number(share) || 0));
}

export function sellThroughColumns() {
  return [
    {
      key: "variant",
      header: "الصنف",
      tone: () => "main",
      text: (r) => variantLabel(r).title,
      sub: (r) => variantLabel(r).detail,
    },
    { key: "season", header: "الموسم", tone: () => "muted", text: (r) => r.season || "—" },
    { key: "sold", header: "اتباع", align: "center", tone: () => "", text: (r) => fmtInt(r.unitsSold) },
    {
      key: "onHand",
      header: "فاضل",
      align: "center",
      tone: (r) => (Number(r.unitsOnHand) === 0 && Number(r.unitsSold) > 0 ? "loss" : ""),
      text: (r) => fmtInt(r.unitsOnHand),
    },
    {
      key: "share",
      header: "نسبة اللي اتباع",
      align: "center",
      tone: (r) => (stockState(r) === "out" ? "strong" : "muted"),
      text: (r) => shareLabel(r.share),
      bar: (r) => barWidth(r.share),
    },
    {
      key: "state",
      header: "الحالة",
      align: "center",
      tone: (r) => (stockState(r) === "out" ? "loss" : "muted"),
      text: (r) => STATE_TEXT[stockState(r)],
    },
  ];
}

/** The totals row, keyed by the same column keys so ReportTable lays it out under the rows. */
export function sellThroughTotalsRow(totals) {
  if (!totals) return null;
  return {
    variant: "الإجمالي",
    season: "",
    sold: fmtInt(totals.unitsSold),
    onHand: fmtInt(totals.unitsOnHand),
    share: shareLabel(totals.share),
    state: "",
  };
}

/** How many sizes are running out and how many sit, for the line above the table. */
export function stateCounts(rows = []) {
  let out = 0;
  let sitting = 0;
  for (const r of rows ?? []) {
    const s = stockState(r);
    if (s === "out") out += 1;
    else if (s === "sitting") sitting += 1;
  }
  return { out, sitting };
}

export function sellThroughSummary(rows = []) {
  const { out, sitting } = stateCounts(rows);
  const parts = [];
  if (out > 0) parts.push(`${fmtInt(out)} مقاس قرّب يخلص`);
  if (sitting > 0) parts.push(`${fmtInt(sitting)} مقاس راكد`);
  return parts.join(" • ");
}

/** The notice shown INSTEAD of the table when the request failed; null when there is nothing to say. */
export function sellThroughErrorNotice(error, kind) {
  if (!error) return null;
  if (kind === "forbidden" || kind === "unauthorized") {
    return {
      kind,
      tone: "forbidden",
      message: "تقرير التصريف لصاحب المحل أو المدير بس. اطلب من المدير يفتحه لك لو محتاجه.",
    };
  }
  if (kind === "offline") {
    return { kind, tone: "failed", message: "تعذّر الوصول للخادم. اتأكد من الاتصال وحاول مرة أخرى." };
  }
  return { kind, tone: "failed", message: "تعذّر تحميل تقرير التصريف. حاول مرة أخرى." };
}
