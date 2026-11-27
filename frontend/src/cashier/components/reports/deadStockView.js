/**
 * What the dead-stock tab draws, as plain data. The rule this file keeps: an unknown cost is shown
 * as unknown (a dash and a warning), NEVER as zero. A size that ties up money we cannot price is the
 * one the owner most needs to look at, and "0" would tell them it costs nothing to keep.
 */
import { fmtInt } from "@/cashier/lib/format";
import { moneyCell, variantLabel } from "@/cashier/components/reports/profitView";

export { errorKind } from "@/cashier/components/reports/profitView";

/** Days since the last sale as text: a number of days, or "ما اتباعش" for a size that never sold. */
export function sinceLabel(row) {
  if (row?.daysSinceSale === null || row?.daysSinceSale === undefined) return "ما اتباعش";
  return `${fmtInt(row.daysSinceSale)} يوم`;
}

/** The value at cost, or a dash when the cost is unknown. Never "0.00" for an unknown cost. */
export function valueLabel(row) {
  return row?.costKnown && row?.value !== null && row?.value !== undefined ? moneyCell(row.value) : "—";
}

export function deadStockColumns() {
  return [
    {
      key: "variant",
      header: "الصنف",
      tone: () => "main",
      text: (r) => variantLabel(r).title,
      sub: (r) => variantLabel(r).detail,
    },
    { key: "season", header: "الموسم", tone: () => "muted", text: (r) => r.season || "—" },
    { key: "onHand", header: "فاضل", align: "center", tone: () => "", text: (r) => fmtInt(r.unitsOnHand) },
    {
      key: "since",
      header: "من آخر بيع",
      align: "center",
      tone: (r) => (r.daysSinceSale === null ? "loss" : "muted"),
      text: (r) => sinceLabel(r),
    },
    {
      key: "value",
      header: "قيمته بالتكلفة",
      align: "end",
      tone: (r) => (r.costKnown ? "strong" : "loss"),
      text: (r) => valueLabel(r),
    },
  ];
}

/** The totals row. The value is the KNOWN part only; the warning says when it is not the whole. */
export function deadStockTotalsRow(totals) {
  if (!totals) return null;
  return {
    variant: "الإجمالي",
    season: "",
    onHand: fmtInt(totals.unitsOnHand),
    since: "",
    value: moneyCell(totals.value),
  };
}

/**
 * The warning when some sizes have no booked cost, or null when every cost is known. Only the
 * server's own "complete" counts: a missing flag is not a promise, so it also warns.
 */
export function costGapWarning(totals) {
  if (!totals) return null;
  const n = Number(totals.withoutCost) || 0;
  if (totals.costIsComplete === true && n === 0) return null;
  if (n > 0) {
    return `القيمة الإجمالية ناقصة: ${fmtInt(n)} مقاس ما له تكلفة شراء مسجّلة، فلم يُحتسب في الرقم. سجّل فواتير الشراء وستكتمل.`;
  }
  return "القيمة الإجمالية قد تكون ناقصة: ليست كل المقاسات لها تكلفة شراء مسجّلة.";
}

/** The header sentence: how long counts as dead. null when the server did not say. */
export function deadStockHeader(days) {
  return days ? `مقاسات فيها رصيد وما اتباعتش من ${fmtInt(days)} يوم أو أكتر` : null;
}

/** The notice shown INSTEAD of the table when the request failed; null when there is nothing to say. */
export function deadStockErrorNotice(error, kind) {
  if (!error) return null;
  if (kind === "forbidden" || kind === "unauthorized") {
    return {
      kind,
      tone: "forbidden",
      message: "تقرير المخزون الراكد يتضمن تكلفة الشراء، فهو لصاحب المتجر، ولا يراه المدير إلا إذا سمح صاحب المتجر بذلك من إعدادات المستخدمين. اطلبه من صاحب المتجر إن كنت تحتاجه.",
    };
  }
  if (kind === "offline") {
    return { kind, tone: "failed", message: "تعذّر الوصول للخادم. اتأكد من الاتصال وحاول مرة أخرى." };
  }
  return { kind, tone: "failed", message: "تعذّر تحميل تقرير المخزون الراكد. حاول مرة أخرى." };
}
