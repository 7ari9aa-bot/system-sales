/**
 * Sell-through, read from GET /reports/sell-through: for each model, colour and size, how many
 * pieces sold in the period and how many are still on the shelf, so the owner sees which size is
 * about to run out and which one sits. The server decides every figure (units sold are the profit
 * report's own, net of returns); this file only shapes the answer. The query is the profit
 * report's (same half-open period, same brand / season / material filters), so it is reused as is.
 *
 * sold_share arrives as text with one decimal ("62.5") or null when nothing sold and nothing is
 * left. It is a percentage the server already rounded, so it is read as a number, never recomputed.
 */
import { materialText } from "@/cashier/lib/material";

export { profitQuery as sellThroughQuery } from "./profitReport";

/** A share as a number from 0 to 100, or null when there is nothing to be a share of. */
export function shareValue(v) {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

export function sellThroughRows(apiRows = []) {
  return (apiRows ?? []).map((r) => ({
    id: r.variant_id,
    model: r.model ?? "",
    season: r.season ?? "",
    material: materialText(r.material),
    brandId: r.brand_id ?? null,
    size: r.size ?? "",
    colour: r.colour ?? "",
    unitsSold: Number(r.units_sold ?? 0),
    unitsOnHand: Number(r.units_on_hand ?? 0),
    share: shareValue(r.sold_share),
  }));
}

export function sellThroughTotals(apiTotals) {
  const t = apiTotals ?? {};
  return {
    unitsSold: Number(t.units_sold ?? 0),
    unitsOnHand: Number(t.units_on_hand ?? 0),
    share: shareValue(t.sold_share),
  };
}
