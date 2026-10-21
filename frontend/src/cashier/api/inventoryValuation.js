/**
 * Stock valuation by category, built from the SAME rows the stock screen shows, so the two can never
 * disagree. An UNKNOWN cost is never treated as zero: a category with unknown-cost variants reports
 * the cost it can prove and says how many variants are missing, because valuing them at 0 would make
 * the shelf look cheaper and the margin look bigger than it is.
 */
import { fromMinor, toMinor } from "./money";
import { STOCK_LIMIT } from "./stockAdapter";

const NO_CATEGORY = "بدون تصنيف";

export function valuationByCategory(rows = []) {
  const map = new Map();
  for (const r of rows) {
    const key = r.category || NO_CATEGORY;
    const g = map.get(key) ?? { id: key, category: key, products: new Set(), variants: 0, pieces: 0, costMinor: 0, retailMinor: 0, unknownCost: 0, retailOfKnownMinor: 0 };
    g.products.add(r.productId);
    g.variants += 1;
    g.pieces += r.stock;
    g.retailMinor += toMinor(r.retailValue);
    if (r.costValue === null || r.costValue === undefined) {
      g.unknownCost += 1;
    } else {
      g.costMinor += toMinor(r.costValue);
      g.retailOfKnownMinor += toMinor(r.retailValue);
    }
    map.set(key, g);
  }
  return [...map.values()]
    .map((g) => ({
      id: g.id,
      category: g.category,
      items: g.products.size,
      variants: g.variants,
      pieces: g.pieces,
      cost: Number(fromMinor(g.costMinor)),
      retail: Number(fromMinor(g.retailMinor)),
      unknownCost: g.unknownCost,
      retailOfKnown: Number(fromMinor(g.retailOfKnownMinor)),
      // margin only over the variants whose cost is known; null when nothing can be proven
      margin: g.retailOfKnownMinor > 0 ? +(((g.retailOfKnownMinor - g.costMinor) / g.retailOfKnownMinor) * 100).toFixed(1) : null,
    }))
    .sort((a, b) => b.retail - a.retail);
}

export function summarizeValuation(groups) {
  const costMinor = groups.reduce((c, g) => c + toMinor(g.cost), 0);
  const retailMinor = groups.reduce((c, g) => c + toMinor(g.retail), 0);
  const knownRetailMinor = groups.reduce((c, g) => c + toMinor(g.retailOfKnown), 0);
  return {
    items: groups.reduce((n, g) => n + g.items, 0),
    variants: groups.reduce((n, g) => n + g.variants, 0),
    pieces: groups.reduce((n, g) => n + g.pieces, 0),
    cost: Number(fromMinor(costMinor)),
    retail: Number(fromMinor(retailMinor)),
    unknownCost: groups.reduce((n, g) => n + g.unknownCost, 0),
    // margin over the variants whose cost is known (null when none): never inflated by unknown costs
    margin: knownRetailMinor > 0 ? +(((knownRetailMinor - costMinor) / knownRetailMinor) * 100).toFixed(1) : null,
    // the screen loads at most STOCK_LIMIT variants: at the cap the totals may be incomplete
    truncated: groups.reduce((n, g) => n + g.variants, 0) >= STOCK_LIMIT,
  };
}
