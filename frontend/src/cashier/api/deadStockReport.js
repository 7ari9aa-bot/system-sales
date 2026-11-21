/**
 * Dead stock, read from GET /reports/dead-stock: sizes with stock on the shelf that have not sold
 * for the shop's own number of days (the owner's setting, `inventory.dead_stock_days`), with the
 * money tied up in them at cost. The server decides who is dead and every figure.
 *
 * The one rule this file exists to keep: an UNKNOWN cost is null, never zero. signedMoney(null) in
 * the profit module is 0 (right for "no discount"), so it is NOT used here: a size whose cost was
 * never booked would read as "ties up 0" and the owner would think it costs nothing to keep.
 */
import { fromMinor, toMinor } from "./money";
import { materialText } from "@/cashier/lib/material";

/** Money as text from the API to a number exact to the cent, or null when the server sent none. */
export function costValue(v) {
  if (v === null || v === undefined || v === "") return null;
  return Number(fromMinor(toMinor(String(v))));
}

/** Days as a whole number, or null for "never sold". A 0 is a real 0 (sold today), not "never". */
export function daysValue(v) {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

export function deadStockRows(apiRows = []) {
  return (apiRows ?? []).map((r) => ({
    id: r.variant_id,
    model: r.model ?? "",
    season: r.season ?? "",
    material: materialText(r.material),
    brandId: r.brand_id ?? null,
    size: r.size ?? "",
    colour: r.colour ?? "",
    unitsOnHand: Number(r.units_on_hand ?? 0),
    lastSoldAt: r.last_sold_at ?? null,
    daysSinceSale: daysValue(r.days_since_last_sale),
    // The server says whether the cost is known; trust that flag, and also treat a missing figure as unknown.
    costKnown: r.cost_known === true && r.stock_value_at_cost != null,
    unitCost: costValue(r.unit_cost),
    value: costValue(r.stock_value_at_cost),
  }));
}

export function deadStockTotals(apiTotals) {
  const t = apiTotals ?? {};
  return {
    variants: Number(t.variants ?? 0),
    unitsOnHand: Number(t.units_on_hand ?? 0),
    value: costValue(t.stock_value_at_cost) ?? 0,
    withoutCost: Number(t.variants_without_cost ?? 0),
    // Only the server's own "true" counts: a missing flag is not a promise that every cost is known.
    costIsComplete: t.cost_is_complete === true,
  };
}

/** The window the server used, so the header can say "no sale for N days". */
export const deadStockDays = (data) => {
  const n = Number(data?.days);
  return Number.isFinite(n) && n > 0 ? n : null;
};
