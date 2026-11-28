/**
 * Season markdown: take a percent off every size of one season, after the owner has seen it.
 * The server decides every price (exact decimal maths, rounded to the cent), flags the sizes that
 * would sell under what the shop paid, and signs the exact set it showed. This file only turns the
 * owner's input into a request and the answer into rows.
 *
 * Two rules it keeps:
 *  - the percent is sent as TEXT ("15", "12.5"), never a float and never a number: 0.1 + 0.2 style
 *    drift on a price list is exactly what exact decimals exist to avoid;
 *  - an unknown cost is null, never zero, so a size is never "under cost" against an invented 0.
 */
import { fromMinor, toMinor } from "./money";

export const MIN_PERCENT = 0.01;
export const MAX_PERCENT = 90;

/**
 * The percent as the exact text to send, or null when it is not a valid percent (empty, not a
 * number, outside 0.01..90, or more than two decimals). Arabic-Indic digits and the Arabic decimal
 * separator are read as the shopkeeper typed them.
 */
export function percentText(input) {
  if (input === null || input === undefined) return null;
  const latin = String(input)
    .trim()
    .replace(/[٠-٩]/g, (d) => String("٠١٢٣٤٥٦٧٨٩".indexOf(d)))
    .replace("٫", ".")
    .replace(",", ".");
  if (!/^\d+(\.\d{1,2})?$/.test(latin)) return null;
  const n = Number(latin);
  if (!(n >= MIN_PERCENT && n <= MAX_PERCENT)) return null;
  // Strip a redundant trailing zero so "15.0" and "15" are the same request and the token matches.
  return latin.replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
}

const money = (v) => (v === null || v === undefined || v === "" ? null : Number(fromMinor(toMinor(String(v)))));

export function markdownRows(apiRows = []) {
  return (apiRows ?? []).map((r) => ({
    id: r.variant_id,
    productId: r.product_id,
    model: r.model ?? "",
    colour: r.colour ?? "",
    size: r.size ?? "",
    oldPrice: money(r.old_price),
    newPrice: money(r.new_price),
    unitCost: money(r.unit_cost),
    costKnown: r.cost_known === true,
    belowCost: r.below_cost === true,
    atFloor: r.at_floor === true,
  }));
}

export function markdownTotals(apiTotals) {
  const t = apiTotals ?? {};
  return {
    variants: Number(t.variants ?? 0),
    products: Number(t.products ?? 0),
    belowCost: Number(t.below_cost ?? 0),
    atFloor: Number(t.at_floor ?? 0),
    withoutCost: Number(t.without_cost ?? 0),
  };
}

/** A preview answer, shaped for the dialog. The token is kept exactly as the server sent it. */
export function shapePreview(data) {
  return {
    season: data?.season ?? "",
    percent: data?.percent ?? "",
    token: typeof data?.token === "string" ? data.token : "",
    rows: markdownRows(data?.rows ?? []),
    totals: markdownTotals(data?.totals),
  };
}

/** The request body for preview. A blank brand is left out, never sent as an empty string. */
export function previewBody({ season, percent, brandId = "" }) {
  const body = { season: String(season ?? "").trim(), percent: percentText(percent) };
  if (brandId) body.brand_id = brandId;
  return body;
}

/** The request body for apply: the SAME fields the preview was made with, plus its token. */
export function applyBody(preview, brandId = "") {
  const body = { season: preview.season, percent: preview.percent, token: preview.token };
  if (brandId) body.brand_id = brandId;
  return body;
}

/** Why a request failed, as the dialog needs to tell it. 409 means "preview again", not "try again". */
export function markdownErrorKind(error) {
  const status = Number(error?.status);
  if (status === 409) return "stale";
  if (status === 401 || status === 403) return "forbidden";
  if (status === 400 || status === 422) return "invalid";
  if (status === 0) return "offline";
  return "failed";
}
