/**
 * Picking a garment by hand, when there is no label to scan.
 *
 * A clothing shop sells one model in several colours, and each colour in a run of sizes. A cashier
 * holding a piece with a torn or missing label still has to sell it, so the till offers the same
 * three choices the rail does: model, then colour, then size.
 *
 * The rules that live here, not in the dialog:
 *  - a model is one product, whatever number of variants it has;
 *  - a colour with nothing on the shelf is still listed (it tells the cashier the model comes in
 *    that colour) but the size itself is what carries "sold out", so the till can refuse the piece
 *    instead of letting the sale fail at payment;
 *  - sizes read in shop order (XS S M L XL, then numbers), never alphabetically, because "L" before
 *    "M" is how a size run looks wrong to a shopkeeper.
 */
import { foldedIncludes } from "./searchText";

/** A colour that was never entered is not a missing value: it is the one-colour model. */
export const colourLabel = (colour) => (String(colour ?? "").trim() ? String(colour).trim() : "بلا لون");

const sizeLabel = (size) => (String(size ?? "").trim() ? String(size).trim() : "مقاس واحد");

const LETTER_SIZES = ["xxs", "xs", "s", "m", "l", "xl", "xxl", "2xl", "3xl", "4xl", "5xl", "6xl"];

/** Sort key for a size: letter sizes first in run order, then numbers, then anything else. */
export function sizeRank(size) {
  const s = String(size ?? "").trim().toLowerCase();
  const i = LETTER_SIZES.indexOf(s);
  if (i >= 0) return [0, i];
  const n = Number(s);
  if (s !== "" && Number.isFinite(n)) return [1, n];
  return [2, 0];
}

const bySize = (a, b) => {
  const [ra, rb] = [sizeRank(a.label), sizeRank(b.label)];
  return ra[0] - rb[0] || ra[1] - rb[1] || a.label.localeCompare(b.label, "ar");
};

/**
 * The models to offer, optionally narrowed by a typed term (model name, SKU or barcode, folded so
 * Arabic spelling and digits match the way the rest of the till matches).
 */
export function modelsFromCatalog(catalog, term = "") {
  const q = String(term ?? "").trim();
  const groups = new Map();
  for (const v of catalog ?? []) {
    if (q && ![v.productName, v.sku, v.barcode].some((field) => foldedIncludes(field ?? "", q))) continue;
    const key = String(v.productId ?? v.productName ?? v.id ?? "");
    if (!groups.has(key)) {
      groups.set(key, { id: key, name: String(v.productName ?? "").trim() || "صنف بلا اسم", variants: [] });
    }
    groups.get(key).variants.push(v);
  }
  return [...groups.values()]
    .map((model) => {
      const stock = model.variants.map((v) => Number(v.stock) || 0);
      const prices = model.variants.map((v) => Number(v.sellPrice) || 0);
      return {
        ...model,
        colours: [...new Set(model.variants.map((v) => String(v.color ?? "").trim()))],
        sizeCount: model.variants.length,
        inStock: stock.filter((n) => n > 0).length,
        priceFrom: prices.length ? Math.min(...prices) : 0,
      };
    })
    .sort((a, b) => a.name.localeCompare(b.name, "ar"));
}

/** The colour to open a model on: the first one with something on the shelf, else the first. */
export function defaultColour(model) {
  const colours = model?.colours ?? [];
  const inStock = colours.find((colour) =>
    (model?.variants ?? []).some((v) => String(v.color ?? "").trim() === colour && (Number(v.stock) || 0) > 0),
  );
  return inStock ?? colours[0] ?? "";
}

/** The size run of one colour, in shop order, each with its stock and whether it can be sold. */
export function sizesFor(model, colour) {
  const wanted = String(colour ?? "").trim();
  return (model?.variants ?? [])
    .filter((v) => String(v.color ?? "").trim() === wanted)
    .map((v) => {
      const stock = Number(v.stock) || 0;
      return {
        variant: v,
        label: sizeLabel(v.size),
        stock,
        soldOut: stock <= 0,
        price: Number(v.sellPrice) || 0,
      };
    })
    .sort(bySize);
}
