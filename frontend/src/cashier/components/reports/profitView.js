/**
 * What the profit report draws, as plain data: the columns, the cells of a row, the totals row, and
 * the one warning the books demand. Kept out of the .jsx so every rule here can be tested by calling
 * it, with no React and no Radix Select in the way.
 *
 * Two things are deliberately NOT smoothed over:
 *  - a loss-making item has a negative profit and a negative margin, and it must read as a loss;
 *  - a sale whose cost the ledger could not cover carries no cost, so the profit is too high.
 *    The server says how many pieces that is (units_without_cost / cost_is_complete); this file
 *    turns that into a sentence the shopkeeper can act on, and never hides it in a footnote.
 */
import { fmtInt, fmtMoney } from "@/cashier/lib/format";
import { marginLabel } from "@/cashier/api/profitReport";

/** Money for a cell. A loss keeps its minus sign and is never shown as a bare amount. */
export function moneyCell(value) {
  const n = Number(value) || 0;
  return n < 0 ? `-${fmtMoney(Math.abs(n))}` : fmtMoney(n);
}

/** The profit cell is the one a shopkeeper scans first, so a loss is marked for the red class. */
export const isLoss = (row) => Number(row?.profit) < 0;

/**
 * The variant cell: the model, with colour and size under it. A variant with no model still gets a
 * readable label instead of an empty cell, and a missing colour/size is left out rather than
 * printed as a bare " / ".
 */
export function variantLabel(row) {
  const model = String(row?.model ?? "").trim();
  const parts = [row?.colour, row?.size].map((v) => String(v ?? "").trim()).filter(Boolean);
  return { title: model || "بند بلا اسم", detail: parts.join(" / ") };
}

/**
 * The units cell: sold, and returned when anything came back. A return is why a row's revenue is
 * lower than its sales, so it is shown next to the sold count instead of being folded in.
 */
export function unitsText(row) {
  const sold = fmtInt(row?.unitsSold);
  const back = Number(row?.unitsReturned) || 0;
  return back > 0 ? `${sold} (مرتجع ${fmtInt(back)})` : sold;
}

/** The row marker for a cost that is an estimate: a return gave back an averaged cost, not a booked one. */
export const estimateMark = (row) => (row?.costIsEstimate ? "≈" : "");

/**
 * The columns of the table, as data: each cell's TEXT and the TONE it is drawn in. No React here,
 * so a test can ask a column what it would print for a loss-making row without rendering anything.
 * Keys match profitTotalsRow() so ReportTable lays the totals row under the same columns.
 *
 * Tones: "main" (the model), "strong" (a figure that matters), "muted" (a secondary figure),
 * "loss" (red: a negative figure the shopkeeper must see as a loss), "" (plain).
 */
export function profitColumns() {
  return [
    {
      key: "variant",
      header: "الصنف",
      tone: () => "main",
      text: (r) => variantLabel(r).title,
      sub: (r) => variantLabel(r).detail,
    },
    { key: "season", header: "الموسم", tone: () => "muted", text: (r) => r.season || "—" },
    { key: "material", header: "الخامة", tone: () => "muted", text: (r) => r.material || "—" },
    { key: "units", header: "القطع", align: "center", tone: () => "", text: (r) => unitsText(r) },
    { key: "revenue", header: "الإيراد", align: "end", tone: () => "", text: (r) => moneyCell(r.revenue) },
    { key: "cost", header: "التكلفة", align: "end", tone: () => "muted", text: (r) => moneyCell(r.cost) },
    {
      key: "profit",
      header: "الربح",
      align: "end",
      tone: (r) => (isLoss(r) ? "loss" : "strong"),
      text: (r) => moneyCell(r.profit),
      mark: estimateMark,
    },
    {
      key: "margin",
      header: "الهامش",
      align: "center",
      tone: (r) => (isLoss(r) ? "loss" : ""),
      text: (r) => marginLabel(r.margin),
    },
  ];
}

/**
 * The warning the books require, or null when every sold piece had a real cost.
 * The count is the larger of the server's total and the sum over the rows: never added twice, and
 * never understated when the totals object is missing.
 */
export function costWarning(totals, rows = []) {
  const fromTotals = Number(totals?.unitsWithoutCost) || 0;
  const fromRows = (rows ?? []).reduce((sum, r) => sum + (Number(r?.unitsWithoutCost) || 0), 0);
  const pieces = Math.max(fromTotals, fromRows);
  if (totals?.costIsComplete !== false && pieces === 0) return null;
  if (pieces > 0) {
    return `ربح أعلى من الحقيقة: ${fmtInt(pieces)} قطعة اتباعت من غير تكلفة شراء مسجّلة، فتكلفتها محسوبة صفر. سجّل فواتير الشراء وهيتصحّح الرقم.`;
  }
  return "ربح أعلى من الحقيقة: مش كل القطع المباعة ليها تكلفة شراء مسجّلة. سجّل فواتير الشراء وهيتصحّح الرقم.";
}

/**
 * Why a request failed, as the screen needs to tell it. No permission is a different message from
 * a network failure: telling a till operator "try again" when they may not see cost and profit
 * would be advice that never works.
 */
export function errorKind(error) {
  const status = Number(error?.status);
  if (status === 401) return "unauthorized";
  if (status === 403) return "forbidden";
  // A real 0 is the api layer's own network/timeout code. An error with no status at all is not a
  // network failure, and telling the owner "check your connection" would send them to the wrong place.
  if (status === 0) return "offline";
  return "failed";
}

/**
 * The notice the profit tab shows INSTEAD of a table when the request failed: null when there is
 * nothing to say. The no-permission answer is not an error to retry — it names who can open the
 * report, because a cashier seeing "try again" would try forever.
 */
export function profitErrorNotice(error) {
  if (!error) return null;
  const kind = errorKind(error);
  if (kind === "forbidden" || kind === "unauthorized") {
    return {
      kind,
      tone: "forbidden",
      message:
        "تقرير الربح فيه تكلفة الشراء وأرباح المحل، فهو لصاحب المحل أو المدير بس. اطلب من المدير يفتحه لك لو محتاجه.",
    };
  }
  if (kind === "offline") {
    return { kind, tone: "failed", message: "تعذّر الوصول للخادم. اتأكد من الاتصال وحاول مرة أخرى." };
  }
  return { kind, tone: "failed", message: "تعذّر تحميل تقرير الربح. حاول مرة أخرى." };
}

/** The totals row, keyed by the same column keys so ReportTable lays it out under the rows. */
export function profitTotalsRow(totals) {
  if (!totals) return null;
  return {
    variant: "الإجمالي",
    season: "",
    material: "",
    units: fmtInt(totals.unitsSold),
    revenue: moneyCell(totals.revenue),
    cost: moneyCell(totals.cost),
    profit: moneyCell(totals.profit),
    margin: marginLabel(totals.margin),
  };
}

/** The sentence under the table: what the figures are made of, so a number is never just a number. */
export function profitFootnote(totals, rows = []) {
  const notes = [];
  if (totals) notes.push("الإيراد بعد الخصومات والمرتجعات، والتكلفة من شرائح الشراء الفعلية (متوسط متحرك).");
  const estimated = (rows ?? []).filter((r) => r?.costIsEstimate).length;
  if (estimated > 0) notes.push(`≈ ${fmtInt(estimated)} صنف رجّع تكلفة تقديرية: المرتجع اللي رجع للمخزن بياخد متوسط تكلفة البيع.`);
  return notes.join(" ");
}
